# 2026-10-29 整體 Code Review

審查基準：`0ee4a20446120ba6415104ef9b7d8fd946673d5d`，開始前 fetch，遠端更新分支與本機 ahead／behind 為 0／0；前置 `2074e42` 已包含。審查階段僅修改文件與證據；之後的程式修正另記於下方修正驗收，正式模型、原始資料與 PPT 保留。**審查時找到三個待修問題；本報告保留原發現，修正狀態由下方驗收連結說明。**

**後續修正：**使用者已授權修復以下三項，修正與回歸結果見 [review-fixes-20261029](../review-fixes-20261029/README.md)。下列保留修正前的審查發現及證據，行號以審查基準為準。

## 發現（按影響排序）

### CR-01 · P1：重訓／續跑的來源識別沒有核對實際原始資料

位置：[train_identity_batch.py](../../../scripts/train_identity_batch.py#L81) 第 81–90、101–108 行。

控制器直接把歷史 `baseline-manifest.json` 的 `raw` 欄位放入 authority，沒有對目前載入的 `data/rebas` 實際檔案重新計算與核對 SHA。只要歷史 manifest 未變、程式未變，原始資料變動後得到的 source_id 仍相同；resume 只比 checkpoint 的 source_id 與權重 SHA，可能沿用舊資料訓練的 checkpoint，或把新資料訓練結果標成舊來源。這使下一次來源更新／續跑的可重現性失去保證；**沒有證據顯示目前已發布的 v5 權重因此有誤**。

已重現：在獨立 fixture 目錄建立來源描述與一個假 checkpoint，修改 fixture 原始 JSON 後執行 controller，仍回傳 `status=complete`、`reused=true`，source_id 不變。沒有啟動訓練，沒有改正式資料或權重，證據見 [retrain-source-repro.json](retrain-source-repro.json)。

建議：由明確指定的新資料集 manifest 取得來源；逐檔檢查檔案集合、SHA、年度與重複比賽後建立 authority，實際訓練載入器也必須使用同一資料根目錄。來源不符時在任何 worker 啟動或 checkpoint 重用前拒絕；補上「修改一檔、增加一檔、刪除一檔後不能續用」的回歸測試。

### CR-02 · P2：clone 後不能照文件完成 v5 重訓

位置：[train_identity_batch.py](../../../scripts/train_identity_batch.py#L75) 第 75、81–84 行，以及原技術文件 8.4。

控制器要求模型與報告目錄都在 `output/`，原文件卻使用 `--models models/new-candidate`，實測立即拒絕。即使改到 output，控制器仍硬編碼依賴 `output/identity-integration-20261025/execution-spec.json` 與 `baseline-manifest.json`；兩檔均未納入 Git，也沒有 CLI 輸入或建立步驟，乾淨 clone 無法重現此訓練流程。這不阻礙使用已提供的權重或靜態站。

本輪已移除會直接失敗的文件命令，標明前置阻礙，沒有假裝訓練入口已修復。建議把不可變訓練規格與來源清單納入可取得的交付，加入明確參數，並以全新 checkout 測試單一截止日的準備／dry-run 路徑，再允許整批訓練。

### CR-03 · P2：starter 欄位缺少布林型別驗證

位置：[server.py](../../../server.py#L170) 第 170–235 行、[engine.py](../../../src/engine.py#L231) 第 231 行，以及 [engine.js](../../engine.js#L287) 第 287 行。

API 對比分與球數使用嚴格型別檢查，但不檢查 starter。有效情境帶 `starter="false"` 仍會通過 validate_evaluation，接著 `bool("false")` 為 True，誤套先發疲勞曲線；JS 的 `!!b.starter` 也有相同問題。110 球等高球數下會改變疲勞與候選比較。正常網站按鈕送出真正布林值，所以這是 API／外部呼叫的邊界缺陷，不代表目前一般操作必然算錯。

已以 mock 球隊名單重現：False、字串 "false"、空陣列及物件都被接受，後兩種非空值會轉為 True。建議 starter 缺省／null 才推估角色，有提供值時僅接受布林；Python 與 JS 入口一致拒絕字串、數值、陣列及物件，並補測疲勞調整與錯誤輸入。

## README 與文件導覽：本輪已修正

- 首頁新增「目前版本與最新內容」，直達 10/29 網站驗收、本報告、10/26 後續工作、最新 32 頁工作稿與 v5 基準。
- 明示 PR 更新分支與正式網站部署的差異，不把最新本機或分支版本當成 main 已部署。
- QA 索引不再把 10/23 當作最新版；加入 10/25、10/26、10/29，v4 留為歷史。
- 簡報索引只把 10/26 稱為最新工作稿，10/25 稱前一版、10/23 稱原交件；澄清舊影片及截圖的版本。
- 協作指南正式模型更正為 v5，避免讀者使用 v4；模型匯出不再引導直接覆寫 docs/data。
- 技術文件移除錯誤重訓命令，解釋嚴格舊封版收據與後續 UI 差異收據的用途。
- 首頁補上免原始資料的純靜態預覽步驟，與需要原始資料的 Python API 啟動分開。

## 審查範圍與證據

本次人工重點審查 API 輸入／路由、前端資料載入與異步狀態、身份／球隊隔離、當日前截止、代打與換投數值、守位及名單、模型權重契約、增量進件、近況試跑、匯出／封版／恢復與重訓控制器。96 個已追蹤 Python 檔做 AST 檢查、11 個前端 JavaScript 做語法檢查；其餘研究與歷史程式以入口、引用與測試覆蓋盤點，**沒有宣稱所有歷史檔案逐行完成形式驗證或外部安全稽核**。

| 檢查 | 結果 | 證據 |
|---|---|---|
| Python 語法／前端 JS 語法 | 96／11，0 錯誤 | [syntax.json](syntax.json) |
| 完整 Python 單元測試 | 143 通過 | [python-tests.log](python-tests.log) |
| 完整前端測試 | 206 通過 | [javascript-tests.log](javascript-tests.log) |
| 實際模型數值一致性 | 18 組自訂，最大誤差 1.20×10⁻¹⁴；275 場／498 組回放，0 遺漏、0 過期 | [numeric-parity.json](numeric-parity.json) |
| 本輪修改之 Markdown 路徑／章節 | 見連結檢查結果 | [document-links.json](document-links.json) |
| 桌面／手機實際操作 | 沿用同碼版本當日 320／390／1024／1440px 驗收，本輪僅改文件 | [網站操作驗收](../ux-context-20261029/README.md) |

另查回放 `pen=null`：目前 226 打席中 207 份為未換投時刻，匯出器刻意省略相同的換投快照；19 個換投時刻均有獨立 pen，未發現目前資料用錯基準。因此沒有把「pen=null」直接列成缺陷。可再補「已換投但 pen 遺失應拒絕」的異常匯出測試，不得將其誤稱目前 207 份壞檔。

本輪不重新訓練、不更動計算結果。建議先修 CR-01，再處理 CR-02 的可重現入口與 CR-03 的輸入契約；完成後跑對應新增回歸測試與既有數值對照。實體觸控與手動離線／儲存拒絕測試仍未完成。這份報告不保證零缺陷，也不代表新球季與多局策略模型已完成。
