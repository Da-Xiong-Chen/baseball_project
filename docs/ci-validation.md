# PR 自動檢查與完整資料驗收

## PR 檢查

GitHub Actions 的 PR validation 使用 Python 3.11、Node.js 22 與 requirements.txt 的固定套件。對所有 PR 及 main 分支的 push 執行，避免同一個 PR 的分支 push 重複跑兩份檢查；權限為 contents: read，不部署、不使用專案機密，checkout 不保存憑證。官方 Actions 以提交 SHA 固定。

執行相同檢查：

```bash
python -m pip install -r requirements.txt
python scripts/run_ci.py
```

這一層不下載或要求 Rebas 原始逐球資料。包括 Python／前端 JS 語法、目前文件路徑與章節連結、696 份靜態資產、全部前端測試，以及來源清單、checkpoint、輸入契約及發布等合成 fixture Python 測試。最新文件清單由 scripts/check_repository.py 的 CURRENT_DOCS 管理；新主導覽文件需加入清單。外部網站連結不在這個離線檢查範圍。

真正無原始資料的 checkout 可加 `--require-no-raw`；如果 data/rebas 存在就拒絕，避免把本機有資料的通過誤稱乾淨 CI 證據。原始模型訓練與完整 Python／回放數值驗收不在這層。檢查日誌保存在忽略追蹤的 output/ci-validation；runner 以任何失敗的子程序結束碼作為整體結果，並保留開發者原有的歷史測試 fixture。

## 完整資料驗收

有既有原始資料的環境仍執行完整 Python 測試、tests/verify_decisions.py、實際瀏覽器操作及需要時的候選模型驗收。CI 通過不代表模型效果已證實，也不能取代完整資料驗收。

目前不設定或變更主分支保護規則；維護者可在 PR 檢查實際成功後，再決定是否將其設為合併條件。新工作流程第一次是否需要核准執行，依 GitHub 專案設定，不預先宣稱雲端 CI 已通過。

## 異常瀏覽器測試

換打、換投、兩分頁名單保存和回放有共用的瀏覽器驗收腳本。先依 [README](../README.md) 啟動靜態站或 API，再用已安裝 Playwright 的 Node 環境執行：

```powershell
$env:BASEBALL_QA_URL = 'http://127.0.0.1:8042/'
node tests/browser_closeout.cjs
```

`BASEBALL_QA_BROWSER=webkit` 可測 WebKit。若 Playwright 套件在其他路徑，用 `PLAYWRIGHT_PACKAGE` 指定；若以現有 Chrome 執行，可用 `BASEBALL_QA_EXECUTABLE` 指定執行檔。腳本使用新的瀏覽器環境，會在同一環境開兩個分頁測名單，測完即關閉。WebKit 測試與 Safari 實機測試分開記錄。

僅本機可用的故障測試站：

```bash
python tests/browser_fault_server.py --port 8030
```

控制頁 `http://127.0.0.1:8030/__qa__/controls` 可模擬模型／回放 HTTP 503 與延遲，再以同站網站操作恢復。`/__qa__/storage-denied` 在不允許同源的 sandbox iframe 內載入網站，讓瀏覽器真的拒絕 localStorage；不是修改使用者瀏覽器權限或假造應用程式回傳。測試站只綁 127.0.0.1，不複製到 docs 或公開部署。

本輪狀態與證據見 [發布前驗收](qa/release-readiness-20261029/README.md)。

## 發布與回復核對

1. 審查時記錄提交 SHA、PR 檢查、單日回放批次 ID、逐球模型截止日。用 `python scripts/prepare_site.py --output output/<新發布目錄>` 產生含逐檔 SHA-256 的發布清單。
2. 維護者合併並部署後，在公開站以新瀏覽器環境和保有舊快取的環境測試。先比對 HTML 中的 CSS／JS 版本，再查回放索引、個別打席、舊連結和簡報下載。確認公開 HTML 來自合併版本後，才記錄部署通過。
3. 若錯版，先核對 Pages 部署 SHA 和公開 HTML。HTML 正確時比較新舊瀏覽器，若乾淨環境也失敗，查回放索引及資料檔的 HTTP 狀態、批次和雜湊。將受影響網址、最後可用版本與測試結果交給維護者，依其流程回復整批資產。
