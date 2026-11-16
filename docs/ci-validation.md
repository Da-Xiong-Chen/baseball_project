# PR 自動檢查與完整資料驗收

## PR 檢查

GitHub Actions 的 PR validation 使用 Python 3.11、Node.js 22 與 requirements.txt 的固定套件。對所有 PR 及 main 分支的 push 執行，避免同一個 PR 的分支 push 重複跑兩份檢查；權限為 contents: read，不部署、不使用專案機密，checkout 不保存憑證。官方 Actions 以提交 SHA 固定。

執行相同檢查：

```bash
python -m pip install -r requirements.txt
python scripts/run_ci.py
```

這一層使用已匯出的資料與測試 fixture，包含 Python／前端 JS 語法、文件連結、靜態資產檢查、所有前端單元測試，以及來源清單、checkpoint、輸入契約與已發布回放 API 的 Python 測試。文件清單由 `scripts/check_repository.py` 的 `CURRENT_DOCS` 管理。外部網址另在發布驗收檢查。

真正無原始資料的 checkout 可加 `--require-no-raw`；如果 data/rebas 存在就拒絕，避免把本機有資料的通過誤稱乾淨 CI 證據。原始模型訓練與完整 Python／回放數值驗收不在這層。檢查日誌保存在忽略追蹤的 output/ci-validation；runner 以任何失敗的子程序結束碼作為整體結果，並保留開發者原有的歷史測試 fixture。

## 完整資料驗收

使用 2024–2026 原始資料執行 `python -m unittest discover -s tests`。有重算需求時，另依[八日回放驗收](qa/website-roadmap-20261115/README.md)配置月初權重、日期批次與報告目錄，再跑 `tests/verify_history_day.py`。以實際瀏覽器檢查發布資產及操作流程；候選模型效果依[模型實驗](qa/model-horizons-20261113/README.md)的方法另行評估。

目前不設定或變更主分支保護規則；維護者可在 PR 檢查實際成功後，再決定是否將其設為合併條件。新工作流程第一次是否需要核准執行，依 GitHub 專案設定，不預先宣稱雲端 CI 已通過。

## 異常瀏覽器測試

換打、換投、兩分頁名單保存和回放有共用的瀏覽器驗收腳本。先依 [README](../README.md) 啟動靜態站或 API，再用已安裝 Playwright 的 Node 環境執行：

```powershell
$env:BASEBALL_QA_URL = 'http://127.0.0.1:8042/'
node tests/browser_closeout.cjs
$env:BASEBALL_QA_WIDTHS = '320,390,768,1280'
node tests/browser_multiday.cjs
```

`BASEBALL_QA_BROWSER=webkit` 可測 WebKit。若 Playwright 套件在其他路徑，用 `PLAYWRIGHT_PACKAGE` 指定；若以現有 Chrome 執行，可用 `BASEBALL_QA_EXECUTABLE` 指定執行檔。腳本使用新的瀏覽器環境，會在同一環境開兩個分頁測名單，測完即關閉。WebKit 測試與 Safari 實機測試分開記錄。

僅本機可用的故障測試站：

```bash
python tests/browser_fault_server.py --port 8030
```

控制頁 `http://127.0.0.1:8030/__qa__/controls` 可模擬模型／回放 HTTP 503 與延遲，再以同站網站操作恢復。`/__qa__/storage-denied` 在不允許同源的 sandbox iframe 內載入網站，讓瀏覽器真的拒絕 localStorage；不是修改使用者瀏覽器權限或假造應用程式回傳。測試站只綁 127.0.0.1，不複製到 docs 或公開部署。

`browser_multiday.cjs` 會讓日期清單第一次回傳 HTTP 503，驗證在原連結重試後能回到正確打席，並確認真實結果保持收合。其他操作及發布狀態見[現行發布驗收](project-closeout-20261116.md)。

同一腳本亦驗證跨日情境選單、接守紀錄故障後重試、鍵盤操作、實際接守與無候選原因，以及瀏覽器上一頁、下一頁與頁內錨點。若日期清單的 `evidence_schema` 為 1，發布檢查會要求各日期的 `evidence.json` 批次、打席與當日資料一致。[匯出及稽核方式](qa/replay-evidence-20261116/README.md)

`browser_closeout.cjs` 會測跨隊套用名單時暫時讀不到球員資料的情境。重試後核對球隊、場上投手及新投手球數，再送出評估。另驗證換人與復原只影響當前分頁，即使瀏覽器拒絕寫入仍可操作。重新整理或關閉後開新分頁，兩種模式都會清除本場退場紀錄，球隊模式會回到先前儲存的配置。

換人規則驗收會先試未確認換人時機的操作，再連續換投及逐次復原。一般模式檢查原投手從現任選單、牛棚及容量方案排除。球隊模式檢查代打承接原棒次、退場球員鎖定、接守待確認、備份匯入後也不能移動 DH 棒次。規則依據為 [中職官方棒球規則 §5.10–5.11](https://www.cpbl.com.tw/files/file_pool/1/0p065549820043528193/2025%E6%A3%92%E7%90%83%E8%A6%8F%E5%89%87%28%E5%AE%98%E7%B6%B2%E7%94%A8%29.pdf) 與 [2026 比賽辦法修定公告](https://cpbl.com.tw/news/cont?SId=0Q083639460189930576)。官方當日登錄、死球、局首熱身及傷病例外需依實際場上資訊確認。

## 發布與回復核對

1. 審查時記錄提交 SHA、PR 檢查、各回放日期的批次 ID 與逐球模型截止日。用 `python scripts/prepare_site.py --output output/<新發布目錄>` 產生含逐檔 SHA-256 的發布清單。
2. 維護者合併並部署後，在公開站以新瀏覽器環境和保有舊快取的環境測試。先比對 HTML 中的 CSS／JS 版本，再查回放索引、個別打席、舊連結和簡報下載。確認公開 HTML 來自合併版本後，才記錄部署通過。
3. 若錯版，先核對 Pages 部署 SHA 和公開 HTML。HTML 正確時比較新舊瀏覽器，若乾淨環境也失敗，查回放索引及資料檔的 HTTP 狀態、批次和雜湊。將受影響網址、最後可用版本與測試結果交給維護者，依其流程回復整批資產。
