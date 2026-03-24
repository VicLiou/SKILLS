---
name: code-review
description: 自動偵測基礎分支，多執行緒收集 diff，AI 代理分析後產出結構化 Code Review 報告
---

# Code Review Skill 使用指引

## 檔案結構

```
code-review-skill/
├── SKILL.md
└── scripts/
    ├── code_review.py       # 主程式（Phase 1 收集 / Phase 2 報告）
    ├── agent_worker.py      # 子代理模組（diff 取得 + 儲存至 cr/diff/）
    └── report_generator.py  # 報告生成模組（彙整 + Markdown 輸出）
```

## 輸出路徑

| 類型                        | 路徑                                 |
| --------------------------- | ------------------------------------ |
| 個別檔案 diff（供 AI 分析） | `cr/diff/<filename>_diff.diff`       |
| 個別檔案分析結果（AI 寫入） | `cr/analysis/<filename>_result.json` |
| 彙整報告                    | `cr/report/code_review_report.md`    |

## 執行流程

### Phase 1：收集 diff（Python 多執行緒）

```bash
python /path/to/code-review-skill/scripts/code_review.py --repo /path/to/project
```

- 自動偵測基礎分支（`main` / `master`），可用 `--base-branch` 覆蓋
- 使用最多 10 個執行緒（Work Queue 模式）並行執行 git diff
- 每個執行緒處理一個差異檔案，完成後立即接取下一個
- 結果儲存至 `cr/diff/<filename>_diff.diff`（僅用檔名，不含路徑）

### Phase 2：AI 代理分析（本步驟）

Phase 1 完成後，AI 代理（你）需要：

1. **全面缺陷掃描**：讀取每個 `cr/diff/*_diff.diff` 的內容進行無死角的 Code Review。你的首要任務是找出**所有**業務邏輯、安全性與效能缺陷。
2. **處理預注入的案例提示（選做）**：在部分 `.diff` 檔案的頂端，可能會自動產生包含了 `[CASE-XXX]` 關鍵字的 `AUTO-INJECTED CONTEXT` 區塊。這表示該檔案的變更可能與歷史錯誤高度相關。
3. **標註歷史案例**：請在你找出所有 Bug 之後，一併檢查是否有 Bug 完全符合頂部提示的案例特徵。若確實命中，請將命中案例的 ID 放入輸出的 `matched_case_ids` 陣列中。
4. 將結果寫入對應的 `cr/analysis/*_result.json`。

> **可並行處理**（使用多個工具呼叫同時分析多個檔案以節省時間）

### Phase 3：產出彙整報告與案例等級自動提升（清除 diff 暫存）

```bash
python /path/to/code-review-skill/scripts/code_review.py --report --repo /path/to/project
```

- 執行時，腳本會自動讀取所有 `cr/analysis/*_result.json`。
- 若分析結果中含有 `matched_case_ids`，腳本會透過內部邏輯映射回完整案例內容，並**自動提升該問題的嚴重等級**！
- 最終彙整產出 `cr/report/code_review_report.md`。
- 報告產出後自動刪除 `cr/diff/` 下所有暫存 `.diff` 檔案。

## 分析結果 JSON 格式

每個 `*_result.json` 的內容（精簡欄位以節省 Token）：

```json
{
  "f": "src/相對路徑/檔案.py",
  "i": [
    {
      "cat": "sec",
      "sev": "high",
      "ln": 42,
      "desc": "問題描述（精簡）",
      "sugg": "修改建議（必填）",
      "code": "建議程式碼片段（必填）",
      "matched_case_ids": ["CASE-001"]
    }
  ]
}
```

| 欄位   | 說明         | 允許值                                            |
| ------ | ------------ | ------------------------------------------------- |
| `cat`  | 問題分類     | `bl`（業務邏輯）/ `sec`（安全性）/ `perf`（效能） |
| `sev`  | 嚴重程度     | `critical` / `high` / `medium` / `low` / `info`   |
| `ln`   | 行號（可選） | 整數或 `null`                                     |
| `desc` | 問題描述     | 精簡字串                                          |
| `sugg` | 修改建議     | **必填**，提供具體可操作的修復方式，不得留空      |
| `code` | 建議程式碼   | **必填**，提供修復後的程式碼片段，以利報告渲染    |
| `matched_case_ids` | 命中案例 | **選填**，字串陣列（如 `["CASE-001"]`），如果有的話 |

> 無問題時：`{"f": "檔名", "i": []}`
> JSON 前後不輸出任何說明文字

## 節省 Token 注意事項

- diff 已自動過濾純空白行、超過 500 行截斷
- `desc` / `sugg` 請使用精簡語言
- 可批次讀取多個 `_diff.diff` 後再寫入結果（減少來回次數）

## 等級說明

| 等級       | 適用情境               |
| ---------- | ---------------------- |
| `critical` | 嚴重漏洞、資料遺失風險 |
| `high`     | 高風險，應在合併前修復 |
| `medium`   | 中等風險，建議修復     |
| `low`      | 低風險，可考慮改善     |
| `info`     | 最佳實踐建議           |
