# 2026-10-29 PR 自動檢查與發布前驗收

本輪完成三項工作：PR 自動檢查、異常操作實測，以及單截止日真實訓練／受控中斷／續跑。正式九個模型、原始逐球資料與 PPT 保留；候選未採用，不合併或部署。

## 1. PR 自動檢查

新增 `.github/workflows/pr-checks.yml`，對 PR 與 main 推送執行唯讀檢查，不使用專案機密、不保存 checkout 憑證。官方 Actions 以精確 commit 固定。`scripts/run_ci.py` 不下載原始資料，檢查語法、目前文件連結、靜態資產、全部前端與合成 fixture Python 測試；日誌放在忽略追蹤的 `output/ci-validation/`。

已複製追蹤及本輪預計交付檔案，建立沒有 `data/rebas` 的獨立檔案副本，以 `--require-no-raw` 執行完整 PR 檢查，**208 項前端、45 項 fixture Python 測試通過**。這是本機 Windows／既有套件環境的 raw-free 驗收，雲端 Linux 執行狀態另見 GitHub 檢查，不把本機通過當作雲端通過。

證據：[無原始資料摘要](ci-without-raw-summary.json)、[完整執行輸出](ci-without-raw.log)、[前端測試](javascript-tests.log)、[fixture Python](python-fixtures.log)。

## 2. 異常使用操作與修正

用 `tests/browser_fault_server.py` 綁定 127.0.0.1 的測試站，經可見控制頁產生 HTTP 503、1 秒回放延遲，以及 opaque-origin sandbox iframe。沒有修改使用者瀏覽器的權限、儲存內容或正式網站。

- 模型首次載入失敗：評估停用、顯示重新載入；恢復服務後可重新載入並完成評估。
- 回放載入失敗：顯示錯誤與重試；恢復後按重試即顯示正確比賽。
- 延遲中連續切換台鋼／統一：最後顯示樂天對統一，較早回應未覆蓋最後選擇。
- 儲存被瀏覽器拒絕：可明確恢復預設、套用本次配置並完成評估，訊息說明無法保存，不冒稱已保存。將固定頁尾改為「名單不會跨裝置同步」，避免和儲存拒絕訊息矛盾。
- 取消選人：測得預設 Escape 關閉不穩定，新增明確 keydown 處理；一般頁及儲存受限 iframe 都確認關閉，草稿不變；組字期間 Escape 不關閉，另有回歸測試。明確關閉按鈕亦不改動草稿。

證據：[瀏覽器操作](browser-abnormal.json)、[儲存拒絕下仍可評估](storage-denied-assessment.jpg)、[受限名單](storage-denied-lineup.jpg)、[主控台紀錄](browser-logs.json)。故障期間的 HTTP 503／測試站 API 404 為預期注入或靜態模式偵測，不能當作正常站錯誤；HTTP 503 也不等於作業系統真正離線。未宣稱實體觸控裝置測試。

## 3. 真實候選訓練與續跑

以一個 worker、兩條執行緒，於隔離 `output/` 訓練 `2025-03-01` 截止日。第一次確認工作程序身份及尚未寫入 checkpoint 後，受控停止此 worker；控制器正確記錄 failed 並釋放鎖。確認程序退出後使用相同來源及參數 `--resume`，完成真實訓練；再續跑一次，確認已完成 checkpoint 被重用。

本次訓練用 102,838 球，日期 2024/03/30–2024/10/11，沒有超過截止日。重跑完成約 64 秒。候選模型可載入、8 組煙霧測試預測皆有限，與現役同截止日的這 8 組預測最大差為 0。這不是全季效能驗證，不能作為新模型採用證明；候選 pickle 與原始來源快照留本機、不推送。

證據：[真實訓練／續跑結果](training-smoke.json)、[中斷前](interrupted-progress-before.json)、[中斷後](interrupted-progress-after.json)。九個正式模型的 SHA 均未改變。

## 完整回歸與界線

另修正 Windows 中文路徑測試的子程序輸出解碼，與 UTF-8 子程序明確一致。完整 Python 157 項通過。最新靜態檢查及修訂資產差異見 [verification.json](verification.json)。既有數值驗收仍見[上一輪 18 情境／498 回放](../review-fixes-20261029/numeric-parity.json)；本輪產品程式只增加 Escape 處理及儲存說明，不改評估數學。

[CI／故障測試操作指南](../../ci-validation.md) · [候選模型訓練指南](../../training-v5.md)。正式站合併後驗收與 branch protection 設定仍由維護者的審查／發布流程處理，不自行合併。
