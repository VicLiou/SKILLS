"""
report_generator.py
報告生成模組：彙整所有子代理的分析結果並輸出 Markdown 報告
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


# ─── 常數定義 ───────────────────────────────────────────────────────────────

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
SEVERITY_LABEL = {
    "critical": "🔴 Critical",
    "high":     "🟠 High",
    "medium":   "🟡 Medium",
    "low":      "🔵 Low",
    "info":     "⚪ Info",
}

CATEGORY_MAP = {
    "bl":   "業務邏輯問題",
    "sec":  "安全性問題",
    "perf": "效能問題",
}
CATEGORY_ORDER = ["bl", "sec", "perf"]


# ─── 工具函式 ────────────────────────────────────────────────────────────────

def _expand_issue(issue: dict[str, Any], filename: str) -> dict[str, Any]:
    """將精簡 JSON 欄位展開為完整欄位名稱。"""
    return {
        "file":        filename,
        "category":    issue.get("cat", "bl"),
        "severity":    issue.get("sev", "info"),
        "line":        issue.get("ln"),
        "description": issue.get("desc", ""),
        "suggestion":  issue.get("sugg", ""),
        "code":          issue.get("code", ""),
        "matched_cases": issue.get("matched_cases", []),  # 命中的歷史案例
    }



def _collect_issues(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """從所有子代理結果中展開並收集所有 issue。"""
    issues: list[dict[str, Any]] = []
    for result in results:
        filename = result.get("f", result.get("file", "unknown"))
        raw_issues = result.get("i", result.get("issues", []))
        for issue in raw_issues:
            issues.append(_expand_issue(issue, filename))
    return issues


def _build_summary(issues: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """統計各分類 × 嚴重程度的問題數量。"""
    summary: dict[str, dict[str, int]] = {
        cat: dict.fromkeys(SEVERITY_ORDER, 0) for cat in CATEGORY_ORDER
    }
    for issue in issues:
        cat = issue["category"]
        sev = issue["severity"]
        if cat in summary and sev in summary[cat]:
            summary[cat][sev] += 1
    return summary


def _detect_lang(filename: str) -> str:
    """從檔名判斷程式語言，用於 Markdown code block 左括標記。"""
    return {
        ".py": "python", ".java": "java", ".js": "javascript",
        ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx",
        ".go": "go", ".rb": "ruby", ".php": "php",
        ".cs": "csharp", ".cpp": "cpp", ".cc": "cpp",
        ".c": "c", ".h": "c", ".hpp": "cpp",
        ".kt": "kotlin", ".swift": "swift", ".rs": "rust",
        ".scala": "scala", ".sh": "bash", ".ps1": "powershell", ".sql": "sql",
    }.get(Path(filename).suffix.lower(), "")


def _render_issue_row(issue: dict[str, Any]) -> str:

    """渲染單一 issue 為 Markdown 條目（含建議程式碼片段）。"""
    line_info = f" (L{issue['line']})" if issue.get("line") else ""
    file_ref = f"`{issue['file']}`{line_info}"
    rows = [
        f"- **{file_ref}**",
        f"  - 問題：{issue['description']}",
    ]
    if issue.get("suggestion"):
        rows.append(f"  - 建議：{issue['suggestion']}")
    if issue.get("code"):
        code_block = issue["code"]
        lang = _detect_lang(issue["file"])
        rows.append("  - 建議程式碼：")
        rows.append(f"    ```{lang}")
        for code_line in code_block.splitlines():
            rows.append(f"    {code_line}")
        rows.append("    ```")
    for mc in issue.get("matched_cases", []):
        rows.append(f"  - ⚠️ 命中歷史案例：**[{mc['id']}]** {mc['title']}")
    return "\n".join(rows)



def generate_report(
    results: list[dict[str, Any]],
    output_path: str | Path = "./code_review_report.md",
    repo_path: str = "",
    branch: str = "",
    base_branch: str = "",
) -> Path:
    """
    彙整分析結果並產出 Markdown 報告。

    Args:
        results:     所有子代理回傳的結構化結果清單
        output_path: 報告輸出路徑
        repo_path:   被審查的 git 專案路徑（僅供報告顯示）
        branch:      當前分支名稱（僅供報告顯示）
        base_branch: 基礎分支名稱（僅供報告顯示）
    Returns:
        輸出報告的 Path 物件
    """
    output_path = Path(output_path)
    issues = _collect_issues(results)
    summary = _build_summary(issues)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(issues)

    lines: list[str] = []

    # ── 標題 ──
    lines += [
        "# Code Review Report",
        "",
        f"- **產生時間**：{now}",
    ]
    if repo_path:
        lines.append(f"- **專案路徑**：`{repo_path}`")
    if branch:
        base_label = base_branch if base_branch else "base"
        lines.append(f"- **分析分支**：`{branch}` vs `{base_label}`")
    lines += [
        f"- **分析檔案數**：{len(results)} 個",
        f"- **發現問題總數**：{total} 個",
        "",
        "---",
        "",
    ]

    # ── 執行摘要 ──
    lines += ["## 執行摘要", ""]
    header = "| 分類 | " + " | ".join(SEVERITY_LABEL[s] for s in SEVERITY_ORDER) + " | 小計 |"
    sep    = "|------|" + "------|" * len(SEVERITY_ORDER) + "------|"
    lines += [header, sep]

    for cat in CATEGORY_ORDER:
        cat_total = sum(summary[cat].values())
        counts = " | ".join(str(summary[cat][sev]) for sev in SEVERITY_ORDER)
        lines.append(f"| {CATEGORY_MAP[cat]} | {counts} | {cat_total} |")

    lines += ["", "---", ""]

    # ── 各分類詳細內容 ──
    for cat in CATEGORY_ORDER:
        cat_issues = [i for i in issues if i["category"] == cat]
        lines += [f"## {CATEGORY_MAP[cat]}", ""]

        if not cat_issues:
            lines += ["> ✅ 此分類無任何問題", "", "---", ""]
            continue

        for sev in SEVERITY_ORDER:
            sev_issues = [i for i in cat_issues if i["severity"] == sev]
            if not sev_issues:
                continue
            lines += [f"### {SEVERITY_LABEL[sev]} ({len(sev_issues)} 個)", ""]
            for issue in sev_issues:
                lines.append(_render_issue_row(issue))
                lines.append("")

        lines += ["---", ""]

    lines.append("> *此報告由 Code Review Skill 自動產出*")
    lines.append("")

    # ── 寫出檔案 ──
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
