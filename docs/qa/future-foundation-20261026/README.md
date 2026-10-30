# 2026-10-26 後續工作：驗收與來源界線

本次更新以未合併的 PR #32／`c8862ee` 為基準；僅推送後續分支供審查，不自行合併或部署。實作範圍見 [說明](../../future-foundation-20261026.md)。

- [瀏覽器實測](browser/report.json)：API／純靜態核心流程、球隊名單保存、單日回放、容量表及其收合草稿修復。容量與回放結果頁四種視窗寬度無頁面溢出；未測部分逐項列明，不把模擬尺寸當實體觸控驗收。
- [前端 198 項](js-tests.log)、[Python 142 項](python-tests.log)。後續只有容量表介面與快取版本修正，未改 Python 模型。
- [推送前數值核對](prepush-decisions.json)：18 組自訂、275 場／498 個回放，0 遺漏、0 過期；最大自訂誤差 1.20×10⁻¹⁴。[靜態資源檢查](prepush-site.log)通過。
- [runtime 轉換收據](runtime-export-receipt.json)：新增年度／日期中繼資料，其他靜態模型欄位與原 v5 完全相同。
- [發布檔案補充清單](release-manifest.json)列出本輪實際網站檔案 SHA；保留 `docs/data/batch-manifest.json` 原 v5 訓練／匯出收據，不將新的程式冒簽成舊訓練來源。
- [進件收據](intake-receipt.json)、[近況事前規格](recency-spec.json)與[單月結果](recency-pilot.json)：沒有採用新權重或接入 2026 資料。
- [簡報結構檢查](ppt-delivery.json)：32 頁、無備忘稿與動畫；第 28–30 頁同步進度，另 29 頁原生內容及媒體保留。原來源的未使用圖片關聯與指定字型可攜性建議保留，無結構錯誤。

`summary-before-browser.json` 保留先前瀏覽器停用時的紀錄；目前核心實測狀態以 `summary.json`、`browser/report.json` 為準。`release_ready=false` 與 `all_tasks_complete=false` 表示未宣稱所有未來研究、規章與完整裝置驗收完成；容量表僅核算使用者設定的打席容量，不判定合法換投義務或多局策略收益。
