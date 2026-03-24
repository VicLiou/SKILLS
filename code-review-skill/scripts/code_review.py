"""
code_review.py
Code Review 主程式：多執行緒收集 diff → AI 代理分析 → 彙整報告

執行流程：
  Phase 1（預設）：多執行緒收集所有差異檔案的 diff，儲存至 cr/analysis/*_diff.md
  Phase 2（--report）：讀取 cr/analysis/*_result.json，產出 cr/report/code_review_report.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# 將 scripts 目錄加入 import 路徑
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from agent_worker import BASE_BRANCH, save_diff_for_analysis
from report_generator import generate_report


# ─── 常數 ────────────────────────────────────────────────────────────────────

DEFAULT_MAX_WORKERS = 10
DIFF_FILTER = "ACM"  # Added / Copied / Modified
CR_ANALYSIS_DIR = "cr/analysis/diff"
CR_REPORT_DIR = "cr/report"


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
    """取得當前分支與 BASE_BRANCH 的差異檔案清單。"""
    output = _run_git(
        ["diff", f"{BASE_BRANCH}...HEAD", "--name-only", f"--diff-filter={DIFF_FILTER}"],
        cwd=repo_path,
    )
    return [f.strip() for f in output.splitlines() if f.strip()]


def get_current_branch(repo_path: str) -> str:
    """取得當前分支名稱。"""
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path).strip()


# ─── 進度追蹤 ────────────────────────────────────────────────────────────────

class _ProgressTracker:
    """執行緒安全的進度追蹤器。"""

    def __init__(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self._lock = threading.Lock()

    def log(self, file_path: str, status: str) -> None:
        with self._lock:
            self.completed += 1
            n = self.completed
        print(f"[{n:>3}/{self.total}] {status}：{file_path}")


# ─── Phase 1：多執行緒收集 diff ──────────────────────────────────────────────

def _collect_worker(
    file_path: str,
    repo_path: str,
    analysis_dir: str,
    progress: _ProgressTracker,
) -> tuple[str, Path | None]:
    """單一執行緒工作：取得 diff 並儲存至 analysis_dir。"""
    try:
        saved_path = save_diff_for_analysis(file_path, repo_path, analysis_dir)
        if saved_path:
            progress.log(file_path, "✓ diff 已儲存")
        else:
            progress.log(file_path, "- 無差異，跳過")
        return file_path, saved_path
    except Exception as e:
        progress.log(file_path, f"✗ 錯誤：{e}")
        return file_path, None


def collect_phase(
    files: list[str],
    repo_path: str,
    analysis_dir: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[Path]:
    """
    Phase 1：使用 ThreadPoolExecutor（Work Queue 模式）並行收集所有檔案的 diff。
    完成的執行緒自動接取下一個檔案，無需手動監控。

    Returns:
        成功儲存的 _diff.md 路徑清單
    """
    total = len(files)
    effective_workers = min(max_workers, total)
    progress = _ProgressTracker(total)

    print(f"[INFO] 共 {total} 個檔案，使用 {effective_workers} 個執行緒收集 diff...\n")
    Path(analysis_dir).mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []

    # Work Queue 模式：ThreadPoolExecutor 自動管理 Queue，
    # 完成的執行緒立即接取下一個 future
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(_collect_worker, f, repo_path, analysis_dir, progress): f
            for f in files
        }
        for future in as_completed(futures):
            _, saved = future.result()
            if saved:
                saved_paths.append(saved)

    return saved_paths


# ─── Phase 2：彙整報告 ───────────────────────────────────────────────────────

def report_phase(
    analysis_dir: str,
    report_dir: str,
    repo_path: str,
    branch: str,
) -> Path | None:
    """
    Phase 2：讀取 analysis_dir 中的 *_result.json，產出彙整報告至 report_dir。

    Returns:
        報告輸出路徑；若無結果檔案則回傳 None
    """
    analysis_path = Path(analysis_dir)
    result_files = sorted(analysis_path.glob("*_result.json"))

    if not result_files:
        print(f"[WARN] 在 {analysis_dir} 中找不到任何 *_result.json 檔案。")
        print("[HINT] 請先讓 AI 代理分析 *_diff.md 並將結果寫入對應的 *_result.json，再執行 --report。")
        return None

    print(f"[INFO] 找到 {len(result_files)} 個分析結果，正在彙整報告...")

    results: list[dict[str, Any]] = []
    for json_file in result_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            results.append(data)
        except Exception as e:
            print(f"[WARN] 讀取 {json_file.name} 失敗：{e}", file=sys.stderr)

    Path(report_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(report_dir) / "code_review_report.md"

    return generate_report(
        results=results,
        output_path=output_path,
        repo_path=repo_path,
        branch=branch,
    )


# ─── 主程式入口 ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Code Review 主程式\n"
            "  不帶 --report：Phase 1 — 多執行緒收集 diff，儲存至 cr/analysis/*_diff.md\n"
            "  帶 --report  ：Phase 2 — 讀取 cr/analysis/*_result.json，輸出彙整報告"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", default=".", help="git 專案根目錄（預設：當前目錄）")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_MAX_WORKERS,
        help=f"最大執行緒數（預設：{DEFAULT_MAX_WORKERS}）",
    )
    parser.add_argument(
        "--analysis-dir", default=CR_ANALYSIS_DIR,
        help=f"diff / 分析結果存放目錄（預設：{CR_ANALYSIS_DIR}）",
    )
    parser.add_argument(
        "--report-dir", default=CR_REPORT_DIR,
        help=f"彙整報告輸出目錄（預設：{CR_REPORT_DIR}）",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="執行 Phase 2：讀取分析結果並產出彙整報告",
    )
    args = parser.parse_args()

    repo_path = str(Path(args.repo).resolve())
    print(f"[INFO] git 專案路徑：{repo_path}")
    print(f"[INFO] 基礎分支：{BASE_BRANCH}")

    branch = get_current_branch(repo_path)

    # ── Phase 2：報告模式 ──
    if args.report:
        output_path = report_phase(args.analysis_dir, args.report_dir, repo_path, branch)
        if output_path:
            print(f"[INFO] ✅ 報告已輸出至：{output_path.resolve()}")
        return

    # ── Phase 1：收集 diff ──
    print("[INFO] 正在取得差異檔案清單...")
    files = get_changed_files(repo_path)

    if not files:
        print(f"[INFO] 當前分支與 {BASE_BRANCH} 無差異，無需進行 Code Review。")
        sys.exit(0)

    print(f"[INFO] 當前分支：{branch}，共 {len(files)} 個差異檔案：")
    for f in files:
        print(f"  - {f}")
    print()

    saved_diffs = collect_phase(files, repo_path, args.analysis_dir, args.workers)

    # 輸出後續操作說明給 AI 代理
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"[✅ Phase 1 完成] {len(saved_diffs)} 個 diff 已儲存至 {args.analysis_dir}/")
    print("\n[NEXT STEP] 請分析以下檔案並將 JSON 結果寫入對應的 _result.json：\n")
    for diff_file in saved_diffs:
        result_name = diff_file.name.replace("_diff.md", "_result.json")
        print(f"  📄 {diff_file}  →  {diff_file.parent / result_name}")
    print("\n[NEXT STEP] 全部分析完成後執行：")
    print(f"  python code_review.py --report --repo {args.repo}")
    print(sep)


if __name__ == "__main__":
    main()
