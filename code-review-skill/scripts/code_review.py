"""
code_review.py
Code Review 主程式：多執行緒收集 diff → AI 代理分析 → 彙整報告

執行流程：
  Phase 1（預設）：自動偵測基礎分支，多執行緒收集差異 diff → cr/diff/*_diff.diff
  Phase 2（--report）：讀取 cr/analysis/*_result.json → cr/report/ 後清除 cr/diff/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# 將 scripts 目錄加入 import 路徑
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from agent_worker import detect_base_branch, save_diff_for_analysis
from case_matcher import match_and_escalate, generate_cases_reference
from report_generator import generate_report


# ─── 常數 ────────────────────────────────────────────────────────────────────

DEFAULT_MAX_WORKERS = 10
DIFF_FILTER = "ACM"        # Added / Copied / Modified
CR_DIFF_DIR = "cr/diff"          # 執行緒儲存 .diff 的目錄
CR_ANALYSIS_DIR = "cr/analysis"  # AI 代理寫入 JSON 結果的目錄
CR_REPORT_DIR = "cr/report"      # 彙整報告輸出目錄
# 讓 cases 目錄直接綁定在這隻 Python 程式的「上一層/cases」
CR_CASES_DIR = str((_SCRIPTS_DIR.parent / "cases").resolve())

# 僅掃描程式碼相關副檔名（可透過 --extensions 覆蓋）
CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".java", ".js", ".jsx", ".ts", ".tsx",
    ".py", ".go", ".rb", ".php", ".cs",
    ".cpp", ".cc", ".c", ".h", ".hpp",
    ".kt", ".kts", ".swift", ".rs", ".scala",
    ".sh", ".bash", ".ps1",
    ".sql",
})


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


def get_changed_files(repo_path: str, base_branch: str) -> list[str]:
    """取得當前分支與 base_branch 的差異檔案清單。"""
    output = _run_git(
        ["diff", f"{base_branch}...HEAD", "--name-only", f"--diff-filter={DIFF_FILTER}"],
        cwd=repo_path,
    )
    return [f.strip() for f in output.splitlines() if f.strip()]


def filter_code_files(
    files: list[str],
    extensions: frozenset[str] = CODE_EXTENSIONS,
) -> tuple[list[str], list[str]]:
    """
    遠濾非程式碼檔案，僅保留符合副檔名白名單的檔案。

    Returns:
        (code_files, skipped_files) 兩個清單
    """
    code_files, skipped = [], []
    for f in files:
        if Path(f).suffix.lower() in extensions:
            code_files.append(f)
        else:
            skipped.append(f)
    return code_files, skipped


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
    diff_dir: str,
    result_dir: str,
    base_branch: str,
    progress: _ProgressTracker,
) -> tuple[str, Path | None]:
    """單一執行緒工作：取得 diff 並儲存至 diff_dir。"""
    try:
        saved_path = save_diff_for_analysis(file_path, repo_path, diff_dir, result_dir, base_branch)
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
    diff_dir: str,
    result_dir: str,
    base_branch: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[Path]:
    """
    Phase 1：使用 ThreadPoolExecutor（Work Queue 模式）並行收集所有檔案的 diff。
    完成的執行緒自動接取下一個檔案（as_completed 確保動態分派）。

    Returns:
        成功儲存的 _diff.diff 路徑清單
    """
    total = len(files)
    effective_workers = min(max_workers, total)
    progress = _ProgressTracker(total)

    print(f"[INFO] 共 {total} 個檔案，使用 {effective_workers} 個執行緒收集 diff...\n")
    Path(diff_dir).mkdir(parents=True, exist_ok=True)
    Path(result_dir).mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []

    # Work Queue 模式：as_completed 讓完成的執行緒立即接取下一個任務
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(
                _collect_worker, f, repo_path, diff_dir, result_dir, base_branch, progress
            ): f
            for f in files
        }
        for future in as_completed(futures):
            _, saved = future.result()
            if saved:
                saved_paths.append(saved)

    return saved_paths


# ─── Phase 2：彙整報告 + 清理 ────────────────────────────────────────────────

def cleanup_diff_dir(diff_dir: str) -> None:
    """刪除 diff_dir 下所有 .diff 檔案（清理掃描完畢後的暫存 diff）。"""
    diff_path = Path(diff_dir)
    if not diff_path.exists():
        return
    deleted = 0
    for f in diff_path.glob("*_diff.diff"):
        f.unlink()
        deleted += 1
    if deleted:
        print(f"[INFO] 已清除 {diff_dir}/ 下 {deleted} 個暫存 diff 檔案")
    # 若目錄為空則一併移除
    try:
        diff_path.rmdir()
        print(f"[INFO] 已移除空目錄：{diff_dir}/")
    except OSError:
        pass  # 非空目錄（含其他檔案）則保留


def report_phase(
    analysis_dir: str,
    report_dir: str,
    repo_path: str,
    branch: str,
    diff_dir: str,
    base_branch: str = "",
    cases_dir: str = "",
) -> Path | None:
    """
    Phase 2：讀取 analysis_dir 中的 *_result.json，
    執行案例對比（若 cases_dir 存在），產出彙整報告至 report_dir。
    報告產出後自動清除 diff_dir 下的暫存 diff 檔案。
    """
    analysis_path = Path(analysis_dir)
    result_files = sorted(analysis_path.glob("*_result.json"))

    if not result_files:
        print(f"[WARN] 在 {analysis_dir} 中找不到任何 *_result.json 檔案。")
        print("[HINT] 請先讓 AI 代理分析 cr/diff/*_diff.diff 並將結果寫入 cr/analysis/*_result.json，再執行 --report。")
        return None

    print(f"[INFO] 找到 {len(result_files)} 個分析結果，正在彙整報告...")

    results: list[dict[str, Any]] = []
    for json_file in result_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            results.append(data)
        except Exception as e:
            print(f"[WARN] 讀取 {json_file.name} 失敗：{e}", file=sys.stderr)

    # 案例對比（直接從 Phase 2 解析的 matched_case_ids 查表）
    if cases_dir:
        print("[INFO] 載入歷史案例並處理命中資訊...")
        results = match_and_escalate(
            results=results,
            cases_dir=cases_dir,
        )

    Path(report_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(report_dir) / "code_review_report.md"

    report = generate_report(
        results=results,
        output_path=output_path,
        repo_path=repo_path,
        branch=branch,
        base_branch=base_branch,
    )

    # 報告產出後清除暫存 diff 檔案
    if report:
        cleanup_diff_dir(diff_dir)

    return report


# ─── 主程式入口 ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Code Review 主程式\n"
            "  不帶 --report：Phase 1 — 偵測基礎分支，多執行緒收集 diff → cr/diff/*_diff.diff\n"
            "  帶 --report  ：Phase 2 — 讀取 cr/analysis/*_result.json，輸出報告並清除 cr/diff/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", default=".", help="git 專案根目錄（預設：當前目錄）")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_MAX_WORKERS,
        help=f"最大執行緒數（預設：{DEFAULT_MAX_WORKERS}）",
    )
    parser.add_argument(
        "--diff-dir", default=CR_DIFF_DIR,
        help=f"diff 儲存目錄（預設：{CR_DIFF_DIR}）",
    )
    parser.add_argument(
        "--result-dir", default=CR_ANALYSIS_DIR,
        help=f"JSON 分析結果存放目錄（預設：{CR_ANALYSIS_DIR}）",
    )
    parser.add_argument(
        "--report-dir", default=CR_REPORT_DIR,
        help=f"彙整報告輸出目錄（預設：{CR_REPORT_DIR}）",
    )
    parser.add_argument(
        "--base-branch", default="",
        help="指定基礎分支（留空則自動偵測 main/master）",
    )
    parser.add_argument(
        "--cases-dir", default=CR_CASES_DIR,
        help=f"歷史問題案例庫目錄（預設：{CR_CASES_DIR}，留空則跳過對比）",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="執行 Phase 2：讀取分析結果並產出彙整報告",
    )
    args = parser.parse_args()

    repo_path = str(Path(args.repo).resolve())
    print(f"[INFO] git 專案路徑：{repo_path}")

    # 自動偵測基礎分支（可透過 --base-branch 覆蓋）
    base_branch = args.base_branch or detect_base_branch(repo_path)
    print(f"[INFO] 基礎分支：{base_branch}")

    branch = get_current_branch(repo_path)

    # ── Phase 2：報告模式 ──
    if args.report:
        output_path = report_phase(
            args.result_dir, args.report_dir, repo_path, branch,
            args.diff_dir, base_branch, args.cases_dir,
        )
        if output_path:
            print(f"[INFO] ✅ 報告已輸出至：{output_path.resolve()}")
        return

    # ── Phase 1：收集 diff ──
    print("[INFO] 正在取得差異檔案清單...")
    files = get_changed_files(repo_path, base_branch)

    if not files:
        print(f"[INFO] 當前分支與 {base_branch} 無差異，無需進行 Code Review。")
        sys.exit(0)

    print(f"[INFO] 當前分支：{branch}，共 {len(files)} 個差異檔案")

    # 過濾程式碼副檔名
    code_files, skipped = filter_code_files(files)
    if skipped:
        print(f"[INFO] 跳過 {len(skipped)} 個非程式碼檔案：{', '.join(skipped)}")
    if not code_files:
        print("[INFO] 無程式碼檔案需要掃描。")
        sys.exit(0)

    print(f"[INFO] 將掃描 {len(code_files)} 個程式碼檔案：")
    for f in code_files:
        print(f"  - {f}")
    print()

    saved_diffs = collect_phase(
        code_files, repo_path, args.diff_dir, args.result_dir, base_branch, args.workers
    )

    # 產生案例參考檔供 Phase 2 使用
    cases_ref_path = Path(args.result_dir) / "cases_reference.json"
    if args.cases_dir:
        generate_cases_reference(args.cases_dir, str(cases_ref_path))

    # 輸出後續操作說明給 AI 代理
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"[✅ Phase 1 完成] {len(saved_diffs)} 個 diff 已儲存至 {args.diff_dir}/")
    print("\n[NEXT STEP] (AI Agent) 接下來請依照指示進行分析：")
    if args.cases_dir and cases_ref_path.exists():
        print(f"  1. 首先閱讀 {cases_ref_path} 了解歷史案例庫。")
        print("  2. 分析每個 diff，若發現有缺陷與案例相符，請在其 JSON 輸出內加上 `\"matched_case_ids\": [\"CASE-XXX\"]`。")
    else:
        print("  1. 分析每個 diff。")
    print("\n[需分析的檔案] 將 JSON 結果寫入對應的 _result.json：\n")
    for diff_file in saved_diffs:
        result_name = diff_file.name.replace("_diff.diff", "_result.json")
        result_path = Path(args.result_dir) / result_name
        print(f"  📄 {diff_file}  →  {result_path}")
    print("\n[FINISH] 全部分析完成後執行：")
    print(f"  python code_review.py --report --repo {args.repo}")
    print(sep)


if __name__ == "__main__":
    main()
