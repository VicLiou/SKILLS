"""
agent_worker.py
子代理工作模組：取得單一檔案的 diff 並儲存至 cr/diff/ 供 AI 代理分析
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ─── 常數 ────────────────────────────────────────────────────────────────────

# MAX_DIFF_LINES = 500  # 已取消限制，完整保留所有 diff 內容


# ─── 工具函式 ────────────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: str) -> str:
    """執行 git 指令並回傳 stdout 字串。若指令失敗印出警告後回傳空字串。"""
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


def detect_base_branch(repo_path: str) -> str:
    """
    自動偵測基礎分支名稱（main 或 master）。

    偵測順序：
    1. 嘗試從 remote HEAD 符號參考取得（最可靠）
    2. 列出本地分支，優先選 main，其次 master
    3. 皆無則預設回傳 main
    """
    # 方法一：從 origin/HEAD 取得（e.g. refs/remotes/origin/main）
    result = _run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_path)
    if result.strip():
        branch = result.strip().split("/")[-1]
        if branch in ("main", "master"):
            return branch

    # 方法二：列出本地分支
    result = _run_git(["branch", "--list", "main", "master"], cwd=repo_path)
    branches = [b.strip().lstrip("* ") for b in result.splitlines() if b.strip()]
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"

    # 預設
    return "main"


def _sanitize_filename(file_path: str) -> str:
    """
    將檔案路徑轉換為安全的檔名。
    只取 basename，移除路徑資訊（例：src/app.js → app_js）。
    """
    name = Path(file_path).name  # 只取檔名（不含路徑）
    return re.sub(r"[^\w\-]", "_", name)


def get_file_diff(repo_path: str, file_path: str, base_branch: str) -> str:
    """
    取得單一檔案與 base_branch 的 diff 內容（使用三點語法）。
    過濾純空白行以節省 Token，完整保留所有實質變更。
    """
    raw = _run_git(["diff", f"{base_branch}...HEAD", "--", file_path], cwd=repo_path)

    if not raw:
        return ""

    lines = raw.splitlines()

    # 過濾純空白變更行（僅有 +/- 後接空白）
    filtered = [
        line for line in lines
        if not (len(line) > 1 and line[0] in ("+", "-") and line[1:].strip() == "")
    ]

    return "\n".join(filtered)


def save_diff_for_analysis(
    file_path: str,
    repo_path: str,
    diff_dir: str,
    result_dir: str,
    base_branch: str,
) -> Path | None:
    """
    取得 diff 並儲存至 diff_dir/<filename>_diff.diff 供 AI 代理分析。
    prompt 中明確告知將結果寫入 result_dir/<filename>_result.json。

    Args:
        file_path:   相對於 repo_path 的檔案路徑
        repo_path:   git 專案根目錄
        diff_dir:    diff 輸出目錄（預設：.cub/references/diff）
        result_dir:  JSON 分析結果存放目錄（預設：.cub/references/analysis）
        base_branch: 基礎分支名稱（由 detect_base_branch 自動偵測）

    Returns:
        儲存的 .diff 檔案路徑；若無差異則回傳 None
    """
    diff = get_file_diff(repo_path, file_path, base_branch)
    if not diff:
        return None

    sanitized = _sanitize_filename(file_path)  # 只用檔名（不含路徑）
    output_path = Path(diff_dir) / f"{sanitized}_diff.diff"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # JSON 結果存放完整路徑（告知 AI 代理寫到哪裡）
    result_path = Path(result_dir) / f"{sanitized}_result.json"

    # 組合結構化 prompt（精簡以節省 Token，sugg 標記為必填）
    prompt = (
        f"分析以下 git diff，將 JSON 結果寫入 {result_path}（不含其他文字）：\n"
        f"格式：{{\"f\":\"檔案路徑\",\"i\":[{{\"cat\":\"bl|sec|perf\",\"sev\":\"critical|high|medium|low|info\","
        f"\"ln\":行號或null,\"desc\":\"問題描述\",\"sugg\":\"建議【必填】\",\"code\":\"建議程式碼片段【必填】\"}}]}}\n"
        f"cat: bl=業務邏輯 sec=安全性 perf=效能 | 無問題時 i=[] | sugg/code 必填\n"
        f"---\n"
        f"File: {file_path}\n"
        f"{diff}"
    )

    output_path.write_text(prompt, encoding="utf-8")
    return output_path


# ─── 獨立執行模式（供測試用）────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="子代理工作模組：取得 diff 並儲存至 diff 目錄")
    parser.add_argument("file_path", help="相對於 repo 根目錄的檔案路徑")
    parser.add_argument("--repo", default=".", help="git 專案根目錄（預設：當前目錄）")
    parser.add_argument("--diff-dir", default=".cub/references/diff", help="diff 輸出目錄（預設：.cub/references/diff）")
    parser.add_argument("--result-dir", default=".cub/references/analysis", help="JSON 結果存放目錄（預設：.cub/references/analysis）")
    parser.add_argument("--base-branch", default="", help="基礎分支（留空則自動偵測）")
    args = parser.parse_args()

    base_branch = args.base_branch or detect_base_branch(args.repo)
    print(f"[INFO] 使用基礎分支：{base_branch}")

    result = save_diff_for_analysis(args.file_path, args.repo, args.diff_dir, args.result_dir, base_branch)
    if result:
        print(f"[OK] diff 已儲存至：{result}")
    else:
        print(f"[INFO] {args.file_path} 無差異內容，跳過")
