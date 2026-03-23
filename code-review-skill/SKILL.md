---
name: code-review
description: 自動比對當前分支與 main 分支差異，透過多執行緒子代理並行分析，產出結構化 Code Review 報告
---

# Code Review Skill 使用指引

## 概述

此 Skill 提供 Python 腳本，用於：
1. 取得當前分支與 `main` 的差異檔案
2. 多執行緒（最多 10 個）並行執行子代理分析
3. 收集結果並輸出 Markdown 報告至 `./code_review_report.md`

## 檔案結構

```
code-review-skill/
├── SKILL.md
└── scripts/
    ├── code_review.py       # 主程式（入口）
    ├── agent_worker.py      # 子代理工作模組
    └── report_generator.py  # 報告生成模組
```

## 使用方式

### 前置條件
- Python 3.12+
- 當前目錄或 `--repo` 參數指定的目錄為有效 git 專案
- 存在 `main` 分支

### 執行指令

```bash
# 在 git 專案根目錄執行
python /path/to/code-review-skill/scripts/code_review.py

# 指定 git 專案路徑
python /path/to/code-review-skill/scripts/code_review.py --repo /path/to/your/project

# 指定最大執行緒數（預設 10）
python /path/to/code-review-skill/scripts/code_review.py --workers 5
```

### 輸出

- 分析報告：`./code_review_report.md`（在執行腳本的當前目錄）
- Console：即時顯示分析進度

## AI 代理分析流程

當腳本執行子代理分析時，AI 代理應依照以下步驟：

1. **讀取 diff 內容**：腳本已提供 `git diff main...HEAD -- <file>` 的輸出
2. **分析差異**：針對 diff 的新增（`+`）與刪除（`-`）行進行分析
3. **輸出 JSON**：嚴格按照以下格式輸出，不得有額外文字

### 分析輸出格式（精簡 JSON）

```json
{
  "f": "相對路徑/檔案名稱",
  "i": [
    {
      "cat": "bl",
      "sev": "high",
      "ln": 42,
      "desc": "問題描述（精簡）",
      "sugg": "修改建議（精簡）"
    }
  ]
}
```

### 欄位說明

| 欄位 | 說明 | 允許值 |
|------|------|--------|
| `cat` | 問題分類 | `bl`（業務邏輯）/ `sec`（安全性）/ `perf`（效能） |
| `sev` | 嚴重程度 | `critical` / `high` / `medium` / `low` / `info` |
| `ln` | 行號（可選） | 整數或 `null` |
| `desc` | 問題描述 | 字串，盡量精簡 |
| `sugg` | 修改建議 | 字串，盡量精簡 |

### 節省 Token 注意事項

- `desc` 與 `sugg` 請使用**精簡語言**，避免冗長說明
- 若無問題，回傳 `{"f": "檔名", "i": []}` 即可
- 不要在 JSON 前後輸出任何解釋性文字

## 報告等級說明

| 等級 | 說明 |
|------|------|
| `critical` | 嚴重缺陷，需立即修復（如安全漏洞、資料遺失風險） |
| `high` | 高風險問題，應在合併前修復 |
| `medium` | 中等風險，建議修復 |
| `low` | 低風險，可考慮改善 |
| `info` | 僅供參考的建議或最佳實踐提示 |
