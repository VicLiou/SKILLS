"""
agent_worker.py
子代理工作模組：取得單一檔案的 diff 並儲存至 cr/analysis/ 供 AI 代理分析
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ─── 常數 ────────────────────────────────────────────────────────────────────

BASE_BRANCH = "master"
MAX_DIFF_LINES = 500  # 節省 Token：超過此行數則截斷


# ─── 工具函式 ────────────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: str) -> str:
    """執行 git 指令並回傳 stdout 字串。若失敗則回傳空字串。"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout
    except FileNotFoundError:
        print("[ERROR] 找不到 git 執行檔，請確認 git 已安裝並加入 PATH", file=sys.stderr)
        return ""


def _sanitize_filename(file_path: str) -> str:
    """將檔案路徑轉換為安全的檔名（保留字母數字與底線）。"""
    return re.sub(r"[^\w\-]", "_", file_path)


def get_file_diff(repo_path: str, file_path: str) -> str:
    """
    取得單一檔案與 BASE_BRANCH 的 diff 內容（使用三點語法）。
    節省 Token：移除純空白行、超過 MAX_DIFF_LINES 行時截斷。
    """
    raw = _run_git(["diff", f"{BASE_BRANCH}...HEAD", "--", file_path], cwd=repo_path)

    if not raw:
        return ""

    lines = raw.splitlines()

    # 過濾純空白變更行（僅有 +/- 後接空白）
    filtered = [
        line for line in lines
        if not (len(line) > 1 and line[0] in ("+", "-") and line[1:].strip() == "")
    ]

    # 截斷超長 diff
    truncated = False
    if len(filtered) > MAX_DIFF_LINES:
        filtered = filtered[:MAX_DIFF_LINES]
        truncated = True

    result = "\n".join(filtered)
    if truncated:
        result += f"\n... [diff 已截斷，僅顯示前 {MAX_DIFF_LINES} 行以節省 Token]"
    return result


def save_diff_for_analysis(
    file_path: str,
    repo_path: str,
    analysis_dir: str,
) -> Path | None:
    """
    取得 diff 並儲存至 analysis_dir/<sanitized>_diff.md 供 AI 代理分析。

    Args:
        file_path:    相對於 repo_path 的檔案路徑
        repo_path:    git 專案根目錄
        analysis_dir: 分析輸出目錄（預設：cr/analysis）

    Returns:
        儲存的 .md 檔案路徑；若無差異則回傳 None
    """
    diff = get_file_diff(repo_path, file_path)
    if not diff:
        return None

    sanitized = _sanitize_filename(file_path)
    output_path = Path(analysis_dir) / f"{sanitized}_diff.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 組合精簡 prompt（節省 Token）
    result_filename = f"{sanitized}_result.json"
    prompt = (
        f"分析以下 git diff，輸出 JSON（不含其他文字）存為 {result_filename}：\n"
        f"格式：{{\"f\":\"檔案路徑\",\"i\":[{{\"cat\":\"bl|sec|perf\",\"sev\":\"critical|high|medium|low|info\","
        f"\"ln\":行號或null,\"desc\":\"問題\",\"sugg\":\"建議\"}}]}}\n"
        f"cat: bl=業務邏輯 sec=安全性 perf=效能 | 無問題時 i=[] | desc/sugg 精簡\n"
        f"---\n"
        f"File: {file_path}\n"
        f"{diff}"
    )

    output_path.write_text(prompt, encoding="utf-8")
    return output_path


# ─── 獨立執行模式（供測試用）────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="子代理工作模組：取得 diff 並儲存至分析目錄")
    parser.add_argument("file_path", help="相對於 repo 根目錄的檔案路徑")
    parser.add_argument("--repo", default=".", help="git 專案根目錄（預設：當前目錄）")
    parser.add_argument("--analysis-dir", default="cr/analysis/diff", help="diff 輸出目錄")
    args = parser.parse_args()

    result = save_diff_for_analysis(args.file_path, args.repo, args.analysis_dir)
    if result:
        print(f"[OK] diff 已儲存至：{result}")
    else:
        print(f"[INFO] {args.file_path} 無差異內容，跳過")
