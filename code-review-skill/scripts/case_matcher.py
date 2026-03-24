"""
case_matcher.py
已知問題案例對比模組，提供以下兩個功能：

  inject_relevant_cases_to_diff（Phase 1 注入）：
    讀取 .diff 檔案內容，若發現 diff 內容含有歷史案例關鍵字，
    自動在 diff 最頂部注入 AUTO-INJECTED CONTEXT 提示，供 AI 分析時參考。

  match_and_escalate（Phase 3 查表）：
    讀取 AI 已寫入 matched_case_ids 的分析結果，
    從案例庫查表取得完整案例資訊，並自動提升命中 issue 的嚴重等級。
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


# ─── 案例提示注入（Phase 1） ──────────────────────────────────────────────────

def inject_relevant_cases_to_diff(diff_path: str, cases: list[dict[str, Any]]) -> bool:
    """
    讀取 diff 檔案內容，若發現修改內容符合歷史案例關鍵字，
    則將案例提示注入至 diff 檔案的最上方供 AI 閱讀。
    
    Args:
        diff_path: 已生成的 .diff 檔案路徑
        cases:     預先載入的歷史案例清單
        
    Returns:
        是否有注入任何案例提示
    """
    if not cases:
        return False
        
    diff_file = Path(diff_path)
    if not diff_file.exists():
        return False
        
    content = diff_file.read_text(encoding="utf-8")
    content_lower = content.lower()
    
    matched_cases = []
    for c in cases:
        keywords = c.get("keywords", [])
        if not keywords:
            continue
        # 只要有任何一個關鍵字出現在 diff 中 (不區分大小寫)
        if any(k.lower() in content_lower for k in keywords):
            matched_cases.append(c)
            
    if not matched_cases:
        return False
        
    # 建立注入的字串
    lines = []
    lines.append("=" * 60)
    lines.append("⚠️ [CODE REVIEW SKILL AUTO-INJECTED CONTEXT] ⚠️")
    lines.append("經腳本初步掃描，此檔案的修改內容含有以下歷史案例關鍵字：")
    lines.append("")
    
    for c in matched_cases:
        lines.append(f"  - [{c['id']}] ({c['category']}) {c['title']}")
        if c.get('description'):
            desc = c['description'].replace('\n', ' ')
            lines.append(f"    說明：{desc}")
            
    lines.append("")
    lines.append("👉 請在「全面審查所有 Bug」的同時，特別留意是否發生上述歷史問題。")
    lines.append("👉 若確實發生，請在輸出的 JSON 中加入 `\"matched_case_ids\": [\"...\"]`。")
    lines.append("=" * 60)
    lines.append("")
    lines.append(content)
    
    diff_file.write_text("\n".join(lines), encoding="utf-8")
    return True


# ─── 等級提升 ────────────────────────────────────────────────────────────────

def _escalate_severity(
    current: str,
    target: str,
) -> str:
    """若 current 低於 target，提升至 target；否則保持不變。"""
    if _SEV_RANK.get(current, 0) < _SEV_RANK.get(target, 3):
        return target
    return current


# ─── 主對比流程（Phase 3） ───────────────────────────────────────────────────

def match_and_escalate(
    results: list[dict[str, Any]],
    cases_dir: str,
) -> list[dict[str, Any]]:
    """
    讀取 Phase 2 結果中的 matched_case_ids，將命中案例詳細資訊附加至結果並提升嚴重等級。

    Args:
        results:     所有子代理回傳的結構化結果清單
        cases_dir:   案例庫目錄（預設：cases/）

    Returns:
        更新後的 results（已提升等級並附加 matched_cases）
    """
    cases = load_cases(cases_dir)
    if not cases:
        print("[INFO] 無歷史案例庫，跳過案例對比")
        return results  # 無案例庫，直接回傳原始結果

    cases_map = {c["id"]: c for c in cases if "id" in c}
    total_matched = 0

    for file_result in results:
        issues = file_result.get("i", file_result.get("issues", []))
        for issue in issues:
            # Phase 2 AI 會在 issue 中放入 matched_case_ids: ["CASE-xxx"]
            matched_ids = issue.get("matched_case_ids", [])
            if not matched_ids or not isinstance(matched_ids, list):
                continue

            # 找出命中案例的詳細資訊
            matched_cases = []
            for cid in matched_ids:
                if cid in cases_map:
                    c = cases_map[cid]
                    matched_cases.append({
                        "id": c["id"], 
                        "title": c["title"], 
                        "escalate_to": c["escalate_to"]
                    })
            
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
        print(f"[INFO] 命中歷史案例：{total_matched} 個 issue 等級已自動依據案例提升")

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
