# 2026 專案收尾與發布驗收

## 公開版本

2026-11-16 核對 GitHub Pages，部署提交為 `4cf3cd8ec15ac8139b3a34265b5595b0ae3dc32f`。此版本包含 PR #38 的多日回放、手機候選快比、代打接守預覽、牛棚 A／B、調度復原及球隊名單備份。

- 公開 HTML、JS、CSS、自訂評估模型、日期清單、兩個日期索引及 4/1 代表打席，共八份資產的 SHA-256 與該提交相符。
- 以 Edge 瀏覽器在 320、390、768、1280 CSS px 重跑公開站操作，包含變更日期、指定打席連結、比分篩選、回上一頁、兩次換投與逐次復原、牛棚 A／B，以及球隊名單匯入和匯出。
- 網站涵蓋 **8 個比賽日、24 場、1,873 個打席**。3,746 組攻守視圖及 1,692 筆調度標記均有核對紀錄。
- [公開網站](https://da-xiong-chen.github.io/baseball_project/) · [PR #38](https://github.com/Da-Xiong-Chen/baseball_project/pull/38) · [Pages 部署](https://github.com/Da-Xiong-Chen/baseball_project/actions/runs/43736382036) · [main 自動檢查](https://github.com/Da-Xiong-Chen/baseball_project/actions/runs/43736383836) · [逐日驗收](qa/website-roadmap-20261115/replay-verification.json) · [部署資產比對](qa/project-closeout-20261116/pages.json)

## 回放連結與切換日期

- 日期索引暫時失敗時，原分享網址和重試入口會保留。重試成功後會回到該日期、比賽、打席與攻守視角，實際結果維持收合。Edge 實測先回傳 HTTP 503，再由使用者點「重新載入日期」。
- 切換日期會清掉前一日的畫面與資料。單元測試涵蓋從 A 切到 B 再回到 A 時，舊請求失敗不會蓋掉新載入的調度標記。配球比較使用請求自己的日期與回放批次。
- 靜態站使用 Edge 在 320、390、768、1280 CSS px 重跑多日回放與核心操作，本機 API 另於 390 px 重跑。233 項 JavaScript 測試通過。完整 Python 測試共 173 項，170 項通過，3 項跳過舊版專用案例。重新匯出後比對 2,951 份發布資產，差異限於 `app.js` 與 `index.html`。
- [PR #39](https://github.com/Da-Xiong-Chen/baseball_project/pull/39) 包含回放連結、日期切換修正、本機 API 改善及文件同步。核對公開部署請依 [CI 說明](ci-validation.md#發布與回復核對)。

## 本機 API 收尾

使用 `start_server.py` 時，自訂評估用 2024–2026 季後模型。歷史回放依日期使用各自的批次。隨專案提供的 2026 權重目錄只含季後模型，所以本機回放 API 會在找不到當月權重時，讀取同日期的已匯出回放，並查核日期、模型批次、截止日及個別打席 SHA-256。當月權重已配置的環境仍可重算。未公開的日期需要配置對應的月初權重及批次。

新增 API 回歸測試，涵蓋破損檔案、未發布日期、4/1 月初同日及已裝權重時的重算路徑。以實際三季資料另呼叫八個日期的代表打席，代打及換投共 16 次均通過。再啟動 2026 Python 伺服器，檢查 HTTP 回放以及 Edge 390px 的評估、名單及回放流程。 [本機 API 驗收](qa/project-closeout-20261116/native-api.json)

完整 Python 測試共 173 項，170 項通過，3 項依舊版匯出檔是否存在而跳過。另以無原始資料的 CI 流程驗證 231 項 JavaScript 測試、Python fixture、網站資產及文件連結。

## 保留的模型與結果

| 用途 | 內容 |
|---|---|
| 自訂評估 | 2024–2026 三季逐球資料，季後模型截止 2027-01-01（排除截止日） |
| 已發布歷史回放 | 階層式模型只用賽日以前的資料，逐球模型只用該月月初以前的資料 |
| 2026 換投時機 | 360 場、12,075 個決策點。實際續投時，有提示組減無提示組的 RE24 差 +0.013 分／打席，95% 區間 −0.012 至 +0.037 |
| 三棒疲勞驗證 | 9,044 個視窗。開啟現行疲勞項後 MSE 增加 0.000845。使用新賽季未參與開發的比賽作為下一次權重採用依據 |

[換投時機回測](qa/timing-2026/README.md) · [疲勞與校準紀錄](qa/website-roadmap-20261115/README.md)

## 交付與維護

- 簡報索引同時提供競賽原交件及 2026 換投時機的補充版 PPT／PDF。補充版保留當時的網站展示畫面，第 13–14 頁更新為 2026 換投時機數字。 [簡報索引](../presentations/competition-2026/README.md) · [38 頁檔案驗收](qa/project-closeout-20261116/presentation.json)
- 工作區可用 `python scripts/prepare_site.py --output output/<新目錄>` 匯出網站與逐檔 SHA-256。本次匯出含 2,951 份資產。日後發布先核對 `main`、部署 SHA、日期索引、核心頁資產，再用實際瀏覽器重跑代表案例。 [本機執行](../README.md#本機執行) · [發布與回復方式](ci-validation.md#發布與回復核對) · [網站匯出收據](qa/project-closeout-20261116/site-bundle.json)
- 下一賽季拿到首批比賽後，先固定候選模型與指標，再開始每週向前驗證。二軍逐球、即時登錄和即時賽況依可用資料與再利用條件規劃。 [季中迭代](qa/season-iteration-2026/README.md) · [資料來源](../資料來源.md)
