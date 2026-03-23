"""
code_review.py
Code Review 主程式：協調整個分析流程
- 取得差異檔案清單
- 使用 ThreadPoolExecutor（最多 10 個執行緒）動態分派子代理
- 收集結果並產出 Markdown 報告
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# 將 scripts 目錄加入 import 路徑
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from agent_worker import analyze_file
from report_generator import generate_report


# ─── 常數 ────────────────────────────────────────────────────────────────────

DEFAULT_MAX_WORKERS = 10
DIFF_FILTER = "ACM"  # Added / Copied / Modified


# ─── Git 工具函式 ─────────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: str) -> str:
    """執行 git 指令並回傳 stdout，失敗回傳空字串。"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"[WARN] git 指令失敗：{' '.join(args)}\n{result.stderr.strip()}", file=sys.stderr)
        return result.stdout
    except FileNotFoundError:
        print("[ERROR] 找不到 git 執行檔，請確認 git 已安裝並加入 PATH", file=sys.stderr)
        sys.exit(1)


def get_changed_files(repo_path: str) -> list[str]:
    """取得當前分支與 main 分支的差異檔案清單。"""
    output = _run_git(
        ["diff", "main...HEAD", "--name-only", f"--diff-filter={DIFF_FILTER}"],
        cwd=repo_path,
    )
    files = [f.strip() for f in output.splitlines() if f.strip()]
    return files


def get_current_branch(repo_path: str) -> str:
    """取得當前分支名稱。"""
    output = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return output.strip()


# ─── 進度追蹤 ────────────────────────────────────────────────────────────────

class _ProgressTracker:
    """執行緒安全的進度追蹤器。"""

    def __init__(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        with self._lock:
            self.completed += 1
            return self.completed

    def print_progress(self, file_path: str) -> None:
        completed = self.increment()
        print(f"[{completed:>3}/{self.total}] 完成分析：{file_path}")


# ─── Work Queue 多執行緒分派 ──────────────────────────────────────────────────

def _worker_task(
    file_path: str,
    repo_path: str,
    ai_analyze_fn: Any,
    progress: _ProgressTracker,
) -> dict[str, Any]:
    """單一工作執行緒的任務函式。"""
    try:
        result = analyze_file(file_path, repo_path, ai_analyze_fn)
    except Exception as e:
        print(f"[ERROR] 分析 {file_path} 時發生例外：{e}", file=sys.stderr)
        result = {"f": file_path, "i": [], "_error": str(e)}
    finally:
        progress.print_progress(file_path)
    return result


def run_analysis(
    files: list[str],
    repo_path: str,
    ai_analyze_fn: Any,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[dict[str, Any]]:
    """
    使用 ThreadPoolExecutor 動態分派子代理分析所有差異檔案。
    完成的執行緒立即接收下一個任務（Work Queue 模式）。

    Args:
        files:          待分析的檔案路徑清單
        repo_path:      git 專案根目錄路徑
        ai_analyze_fn:  AI 分析函式（接收 prompt 字串，回傳 JSON 字串）
        max_workers:    最大執行緒數（預設 10）

    Returns:
        所有子代理回傳的結構化結果清單
    """
    total = len(files)
    progress = _ProgressTracker(total)
    results: list[dict[str, Any]] = []

    effective_workers = min(max_workers, total)
    print(f"[INFO] 共 {total} 個檔案，使用 {effective_workers} 個執行緒分析中...\n")

    # ThreadPoolExecutor 搭配 submit 實現動態 Work Queue：
    # 每個 future 完成後立即接收下一個任務，確保執行緒數量始終飽和
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(_worker_task, f, repo_path, ai_analyze_fn, progress): f
            for f in files
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                file_path = futures[future]
                print(f"[ERROR] {file_path} 的 future 執行失敗：{e}", file=sys.stderr)
                results.append({"f": file_path, "i": [], "_error": str(e)})

    return results


# ─── AI 分析函式（預設實作：輸出 prompt 並等待使用者輸入）────────────────────

def _default_ai_analyze_fn(prompt: str) -> str:
    """
    預設 AI 分析函式：將 prompt 印出後，由使用此 Skill 的 AI 代理從 stdin 讀取結果。
    若從管道（pipe）讀取，則直接讀取 stdin；否則提示使用者輸入。
    """
    print("\n" + "=" * 60)
    print(prompt)
    print("=" * 60)

    if not sys.stdin.isatty():
        # 管道模式：從 stdin 讀取完整輸入（直到 EOF）
        return sys.stdin.read()
    else:
        # 互動模式：提示輸入（按 Ctrl+Z / Ctrl+D 結束）
        print("[PROMPT] 請輸入 JSON 分析結果（結束後按 Ctrl+Z (Windows) 或 Ctrl+D (Unix)）：")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        return "\n".join(lines)


# ─── 主程式入口 ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Code Review 主程式：分析當前分支與 main 的差異並產出報告"
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="git 專案根目錄路徑（預設：當前目錄）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"最大執行緒數（預設：{DEFAULT_MAX_WORKERS}）",
    )
    parser.add_argument(
        "--output",
        default="./code_review_report.md",
        help="報告輸出路徑（預設：./code_review_report.md）",
    )
    args = parser.parse_args()

    repo_path = str(Path(args.repo).resolve())
    print(f"[INFO] git 專案路徑：{repo_path}")

    # 1. 取得差異檔案清單
    print("[INFO] 正在取得差異檔案清單...")
    files = get_changed_files(repo_path)

    if not files:
        print("[INFO] 當前分支與 main 無差異，無需進行 Code Review。")
        sys.exit(0)

    branch = get_current_branch(repo_path)
    print(f"[INFO] 當前分支：{branch}，共 {len(files)} 個差異檔案：")
    for f in files:
        print(f"  - {f}")
    print()

    # 2. 執行多執行緒分析（Work Queue 模式）
    results = run_analysis(
        files=files,
        repo_path=repo_path,
        ai_analyze_fn=_default_ai_analyze_fn,
        max_workers=args.workers,
    )

    # 3. 產出報告
    print(f"\n[INFO] 正在產出報告...")
    output_path = generate_report(
        results=results,
        output_path=args.output,
        repo_path=repo_path,
        branch=branch,
    )
    print(f"[INFO] ✅ 報告已輸出至：{output_path.resolve()}")


if __name__ == "__main__":
    main()
