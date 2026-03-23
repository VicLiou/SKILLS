"""
agent_worker.py
子代理工作模組：取得單一檔案的 diff 內容，供 AI 代理分析後回傳結構化結果
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# ─── 常數 ────────────────────────────────────────────────────────────────────

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


def _get_file_diff(repo_path: str, file_path: str) -> str:
    """
    取得單一檔案與 main 分支的 diff 內容（使用三點語法）。
    節省 Token：移除純空白行、超過 MAX_DIFF_LINES 行時截斷。
    """
    raw = _run_git(["diff", "main...HEAD", "--", file_path], cwd=repo_path)

    if not raw:
        return ""

    lines = raw.splitlines()

    # 過濾純空白變更行（僅有 +/- 後接空白）
    filtered: list[str] = []
    for line in lines:
        if len(line) > 1 and line[0] in ("+", "-") and line[1:].strip() == "":
            continue
        filtered.append(line)

    # 截斷超長 diff
    truncated = False
    if len(filtered) > MAX_DIFF_LINES:
        filtered = filtered[:MAX_DIFF_LINES]
        truncated = True

    result = "\n".join(filtered)
    if truncated:
        result += f"\n... [diff 已截斷，僅顯示前 {MAX_DIFF_LINES} 行以節省 Token]"

    return result


def _build_analysis_prompt(file_path: str, diff_content: str) -> str:
    """
    建立給 AI 代理的分析提示（精簡版，節省 Token）。
    """
    return (
        f"分析以下 git diff，輸出 JSON（不含其他文字）：\n"
        f"格式：{{\"f\":\"檔案路徑\",\"i\":[{{\"cat\":\"bl|sec|perf\",\"sev\":\"critical|high|medium|low|info\",\"ln\":行號或null,\"desc\":\"問題\",\"sugg\":\"建議\"}}]}}\n"
        f"cat: bl=業務邏輯 sec=安全性 perf=效能\n"
        f"無問題時 i=[]，desc/sugg 精簡\n"
        f"---\n"
        f"File: {file_path}\n"
        f"{diff_content}"
    )


def analyze_file(
    file_path: str,
    repo_path: str,
    ai_analyze_fn: Any,
) -> dict[str, Any]:
    """
    分析單一檔案並回傳結構化結果。

    Args:
        file_path:      相對於 repo_path 的檔案路徑
        repo_path:      git 專案根目錄的絕對路徑
        ai_analyze_fn:  接收 prompt 字串並回傳分析結果 JSON 字串的函式
                        （由主程式或 AI 代理的呼叫者提供）

    Returns:
        dict 格式：{"f": "檔案路徑", "i": [...issue list...]}
    """
    diff_content = _get_file_diff(repo_path, file_path)

    if not diff_content:
        # 無差異或取得失敗：回傳空結果
        return {"f": file_path, "i": []}

    prompt = _build_analysis_prompt(file_path, diff_content)

    try:
        raw_response: str = ai_analyze_fn(prompt)
        # 嘗試從回應中提取 JSON（防止 AI 在 JSON 前後加入說明文字）
        raw_response = raw_response.strip()
        # 若回應包含 markdown code block，提取其中內容
        if "```" in raw_response:
            parts = raw_response.split("```")
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("{"):
                    raw_response = stripped
                    break
        result = json.loads(raw_response)
        # 確保 "f" 欄位存在
        result["f"] = result.get("f", file_path)
        return result
    except (json.JSONDecodeError, Exception) as e:
        print(f"[WARN] 解析 {file_path} 的分析結果失敗：{e}", file=sys.stderr)
        return {"f": file_path, "i": [], "_error": str(e)}


# ─── 獨立執行模式（供測試用）────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="子代理工作模組（測試模式：僅輸出 diff 內容）")
    parser.add_argument("file_path", help="相對於 repo 根目錄的檔案路徑")
    parser.add_argument("--repo", default=".", help="git 專案根目錄（預設：當前目錄）")
    args = parser.parse_args()

    diff = _get_file_diff(args.repo, args.file_path)
    if diff:
        print(f"=== {args.file_path} 的 diff 內容 ===")
        print(diff)
        print(f"\n=== AI 分析提示（節省 Token 版）===")
        print(_build_analysis_prompt(args.file_path, diff))
    else:
        print(f"[INFO] {args.file_path} 無差異內容或取得失敗")
