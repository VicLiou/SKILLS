"""
case_matcher.py
已知問題案例對比模組：將掃描 issue 與歷史案例庫比對，命中則提升等級至 high

兩層預篩策略（節省 Token）：
  層一：分類隔離 — issue.cat == case.category（Python 比對，免費）
  層二：關鍵字預篩 — case.keywords 至少一個出現在 issue.desc/sugg（Python 比對，免費）
  → 僅將「預篩命中」的候選案例送給 AI 做語意比對
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 嚴重程度排序（數值越大越嚴重）
_SEV_RANK: dict[str, int] = {
    "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4
}


# ─── 案例讀取 ────────────────────────────────────────────────────────────────

def load_cases(cases_dir: str) -> list[dict[str, Any]]:
    """
    讀取 cases_dir 下所有 *.json 案例檔。

    Returns:
        案例物件清單；若目錄不存在或無案例則回傳空清單
    """
    cases_path = Path(cases_dir)
    if not cases_path.is_dir():
        return []

    cases = []
    for json_file in sorted(cases_path.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            # 確保必要欄位存在
            if all(k in data for k in ("id", "title", "keywords", "category")):
                data.setdefault("escalate_to", "high")
                cases.append(data)
        except Exception as e:
            print(f"[WARN] 讀取案例 {json_file.name} 失敗：{e}", file=sys.stderr)

    print(f"[INFO] 載入 {len(cases)} 個歷史問題案例")
    return cases


# ─── 兩層預篩 ────────────────────────────────────────────────────────────────

def _prefilter_candidates(
    issue: dict[str, Any],
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    兩層預篩：分類隔離 → 關鍵字比對，回傳候選案例列表。
    全程 Python str 比對，不消耗 Token。
    """
    issue_cat = issue.get("category", "")
    issue_text = (
        (issue.get("description", "") + " " + issue.get("suggestion", "")).lower()
    )

    candidates = []
    for case in cases:
        # 層一：分類隔離
        if case.get("category", "") != issue_cat:
            continue
        # 層二：關鍵字預篩（至少一個 keyword 出現在 issue 文字中）
        keywords = [kw.lower() for kw in case.get("keywords", [])]
        if any(kw in issue_text for kw in keywords):
            candidates.append(case)

    return candidates


# ─── 比對提示生成 ────────────────────────────────────────────────────────────

def build_match_prompt(
    issue: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    """
    生成給 AI 代理的精簡比對提示（節省 Token）。
    代理只需回傳命中的案例 ID 清單（JSON 陣列）。
    """
    # 壓縮案例格式：ID|title|keywords
    case_lines = "\n".join(
        f"{c['id']}|{c['title']}|{','.join(c['keywords'][:5])}"
        for c in candidates
    )
    return (
        f"判斷以下 issue 是否與歷史案例相似，回傳命中的 ID 陣列（如 [\"CASE-001\"]，無命中回傳 []）：\n"
        f"Issue：{issue.get('description', '')} / {issue.get('suggestion', '')}\n"
        f"案例（ID|標題|關鍵字）：\n{case_lines}"
    )


# ─── 等級提升 ────────────────────────────────────────────────────────────────

def _escalate_severity(
    current: str,
    target: str,
) -> str:
    """若 current 低於 target，提升至 target；否則保持不變。"""
    if _SEV_RANK.get(current, 0) < _SEV_RANK.get(target, 3):
        return target
    return current


# ─── 主對比流程 ──────────────────────────────────────────────────────────────

def match_and_escalate(
    results: list[dict[str, Any]],
    cases_dir: str,
    ai_match_fn: Any,
) -> list[dict[str, Any]]:
    """
    對所有掃描結果執行案例對比，命中的 issue 提升等級並標記案例資訊。

    Args:
        results:     所有子代理回傳的結構化結果清單
        cases_dir:   案例庫目錄（預設：cases/）
        ai_match_fn: 接收 prompt 字串，回傳 JSON 陣列字串的函式
                     （由 AI 代理提供，輸入 prompt，輸出 ["CASE-001", ...]）

    Returns:
        更新後的 results（已提升等級）
    """
    cases = load_cases(cases_dir)
    if not cases:
        print("[INFO] 無歷史案例庫，跳過案例對比")
        return results  # 無案例庫，直接回傳原始結果

    total_matched = 0

    for file_result in results:
        issues = file_result.get("i", file_result.get("issues", []))
        for issue in issues:
            candidates = _prefilter_candidates(issue, cases)
            if not candidates:
                continue  # 兩層預篩無候選，跳過（不消耗 Token）

            # 送候選案例給 AI 比對
            prompt = build_match_prompt(issue, candidates)
            try:
                raw = ai_match_fn(prompt).strip()
                # 解析回傳的 ID 陣列
                if raw.startswith("["):
                    matched_ids: list[str] = json.loads(raw)
                else:
                    matched_ids = []
            except Exception:
                matched_ids = []

            if not matched_ids:
                continue

            # 找出命中案例的詳細資訊
            matched_cases = [
                {"id": c["id"], "title": c["title"], "escalate_to": c["escalate_to"]}
                for c in candidates
                if c["id"] in matched_ids
            ]
            if not matched_cases:
                continue

            # 提升等級（取所有命中案例中最高的 escalate_to）
            best_target = max(
                (c["escalate_to"] for c in matched_cases),
                key=lambda s: _SEV_RANK.get(s, 3),
            )
            old_sev = issue.get("sev", issue.get("severity", "info"))
            new_sev = _escalate_severity(old_sev, best_target)

            # 更新 issue（相容精簡欄位 sev 與完整欄位 severity）
            if "sev" in issue:
                issue["sev"] = new_sev
            if "severity" in issue:
                issue["severity"] = new_sev

            issue["matched_cases"] = matched_cases
            total_matched += 1

    if total_matched:
        print(f"[INFO] 命中歷史案例：{total_matched} 個 issue 等級已提升")
    else:
        print("[INFO] 未命中任何歷史案例")

    return results


# ─── 獨立執行模式（供測試用）────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="案例對比模組（測試：列出所有案例）")
    default_cases_dir = str((Path(__file__).parent.parent / "cases").resolve())
    parser.add_argument("--cases-dir", default=default_cases_dir, help=f"案例庫目錄（預設：{default_cases_dir}）")
    args = parser.parse_args()

    loaded = load_cases(args.cases_dir)
    for case in loaded:
        print(f"  [{case['id']}] {case['title']} (cat={case['category']}, escalate_to={case['escalate_to']})")
        print(f"    keywords: {', '.join(case['keywords'][:5])}")
