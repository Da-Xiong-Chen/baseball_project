# 2026-10-29 Code Review 修正與驗收

本輪修復 [整體審查](../code-review-20261029/README.md) 的三項問題，包含 README 最新導覽。基準為 `0ee4a20`，推送採既有 PR #33；不合併或部署。**目前九個 v5 正式模型與網站數值參數保留，沒有執行整批重訓或新模型採用。**

## 修正對照

| 問題 | 修正 | 驗收 |
|---|---|---|
| CR-01 來源改變仍能重用 checkpoint | 每次檢查實際來源檔案集合及 SHA；authority 包含規格、程式、runtime、Python 與套件版本。建立獨立輸入快照，每個 worker 驗證後才讀取，完成後再核對。來源不同或檔案增刪拒絕續跑 | 修改／新增／刪除／重複 JSON 均在啟動 worker 前拒絕；新 manifest 不能沿用舊 checkpoint；相同來源可重用；快照不受外部來源修改影響 |
| CR-02 重訓入口依賴本機隱藏檔及錯誤路徑 | 加入可追蹤的 config/training-v5.json、明確 data-root／source-manifest、prepare-source 及 dry-run。資料根目錄由實際 worker 的 BASEBALL_DATA_ROOT 綁定 | 乾淨程式副本沒有歷史 output，實際 724 檔 dry-run 通過；不建立候選模型或訓練報告；worker 測試替身確認來源、輸出與完成前拒絕變動 |
| CR-03 字串 false 被當先發 | API、Python 情境建立及 JS 引擎只接受布林；缺省／null 保持角色推估。拒絕字串、數值、陣列及物件，更新 JS 快取版本 | 非布林矩陣拒絕、true／false／null／省略正常；後援不套先發疲勞；瀏覽器先發110球、後援110球及代打實際評估通過 |

## 驗收證據

- [完整前端 207 項](javascript-tests.log)，全數通過。
- [完整 Python 153 項](python-tests.log)，全數通過；新增來源與型別測試。
- [Python／JS 數值核對](numeric-parity.json)：18 組自訂情境，最大誤差 1.20×10⁻¹⁴；275 場／498 組回放，0 遺漏、0 過期。
- [乾淨程式副本 dry-run](dry-run-clean.json)：從本輪程式、config 與 requirements 副本執行，沒有歷史 output 或舊 execution-spec／baseline。使用現有原始資料作唯讀來源；不是另外安裝套件的全新作業系統驗收。
- [九個正式權重 SHA 未變](weights-unchanged.json)，active-batch 亦未修改。
- [實際瀏覽器](browser.json)、[評估截圖](browser-assessment.jpg)：重新載入新版純靜態站後，正常角色與代打完成、console warning/error 為 0。
- [文件路徑／章節檢查](document-links.json)、[語法及靜態發布檢查](verification.json)。

## 使用方式

重訓入口與完整命令見 [v5 候選訓練指南](../../training-v5.md)。固定為既有 2024–2025 與九個截止日，其他年度明確拒絕，不能將本次修正當成新年度模型已支援。候選完成後仍須獨立 context／匯出、數值與效果驗收、PR 審查，不會自動替換正式模型。

歷史 checkpoint 缺少新的來源與版本契約時會拒絕續用，應保留原檔並選新候選目錄，不能手動補上來源 ID 冒充驗收。此次測試未訓練九個模型；worker 的寫入流程以測試替身驗證，不將其當成新模型效果證據。實體觸控及人工離線／儲存拒絕測試仍屬先前未測範圍，本輪沒有新增會改變版面或儲存流程的設計。
