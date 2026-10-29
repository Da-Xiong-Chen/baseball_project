# 測試與驗收紀錄

這裡收錄每一輪修改的驗收證據（說明、測試紀錄、截圖與 JSON 結果）。

- **只想看結論**：讀[最新網站驗收](ux-context-20261029/README.md)與[整體程式碼審查](code-review-20261029/README.md)；模型基準見[v5 整合驗收](identity-integration-20261025/README.md)；原交件版另見[初審驗收](competition-ready-20261023/README.md)。
- **想核對某項功能**：依下方分類找對應日期的紀錄。
- 舊紀錄保留作歷史追溯，數字與畫面以當時版本為準；現行說明見 [README](../../README.md) 與 [技術細節](../技術細節.md)。

## 最新

以下依日期列出目前分支的最新證據；不等於全部已合併或部署。10/23 及更早資料保留作歷史對照。

| 日期 | 紀錄 | 重點 |
|---|---|---|
| 10-29 | [review-fixes-20261029/README.md](review-fixes-20261029/README.md) | 修復來源綁定、可重現訓練入口及 starter 布林型別契約；保留原正式權重 |
| 10-29 | [code-review-20261029/README.md](code-review-20261029/README.md) | 整體程式碼審查、可重現缺陷與文件導覽修正；不以測試通過宣稱零缺陷 |
| 10-29 | [ux-context-20261029/README.md](ux-context-20261029/README.md) | 前端 206／Python 143、容量表及名單四尺寸實際操作、單日回放驗收 |
| 10-29 | [ux-refinement-20261029/README.md](ux-refinement-20261029/README.md) | 錯誤欄位定位與鍵盤焦點修正；當時瀏覽器阻礙已由後續 ux-context 驗收補足 |
| 10-26 | [future-foundation-20261026/README.md](future-foundation-20261026/README.md) | 年度設定、720 場進件、近況試跑及 32 頁審閱稿；非新權重採用 |
| 10-25 | [identity-integration-20261025/README.md](identity-integration-20261025/README.md) | 來源 ID、九個 v5 模型與同版匯出基準 |
| 10-23 | [competition-ready-20261023/README.md](competition-ready-20261023/README.md) | 網站與 32 頁初審提案驗收，逐項對照官方六項初審要求；前端、Python、HTTP 回放、數值與 PPT／PDF 檢查全部通過 |
| 10-23 | [content-closeout-20261023/README.md](content-closeout-20261023/README.md) | 網站收尾：181 項前端測試、452 個回放畫面通過；32 頁簡報逐頁檢查並列出待同步項目 |
| 10-23 | [navigation-ux-20261023/README.md](navigation-ux-20261023/README.md) | 上方入口改為一般使用者／球隊／單日分析，補強手機點選與非同步切換 |
| 10-23 | [coverage-motion-prune-20261023/VERIFICATION.md](coverage-motion-prune-20261023/VERIFICATION.md) | 刪除干擾閱讀的淡入動畫；資料不足時改顯示原始配球觀察與條件式防守改位 |
| 10-23 | [usability-motion-20261023/VERIFICATION.md](usability-motion-20261023/VERIFICATION.md) | 以實際瀏覽器執行主要任務，檢查操作流程與介面動態 |

## 模型與數值

現行模型基準為 v5，見上方 10/25 整合紀錄。以下列出較早 v4 模型、回測與網站數值檢查，不能當作最新版數值收據。

| 日期 | 紀錄 | 重點 |
|---|---|---|
| 10-22 | [numeric-audit-20261022/VERIFICATION.md](numeric-audit-20261022/VERIFICATION.md) | 全部 680 份資料檔、約 185 萬個數值逐一檢查，未發現非有限值、比例越界或單位錯誤 |
| 10-22 | [backtest-final-20261022/VERIFICATION.md](backtest-final-20261022/VERIFICATION.md) | 單日分析與模型時間驗證的完整驗收，修正三個錯誤恢復與非同步問題 |
| 10-22 | [final-closeout-20261022/README.md](final-closeout-20261022/README.md) | v4 參賽版本驗收；重抽樣區間完成計算但決定不採用 |
| 10-22 | [final-closeout-20261022/model-uncertainty-result.md](final-closeout-20261022/model-uncertainty-result.md) | 模型不確定性計算（兩組種子共 3,200 次）與跨種子診斷，說明不採用新區間的原因 |
| 10-22 | [final-closeout-20261022/CLOSEOUT.md](final-closeout-20261022/CLOSEOUT.md) | 參賽原型本機收尾：功能完善與交付整理 |

## 功能驗收

各項功能上線時的操作與回歸測試。

| 日期 | 紀錄 | 重點 |
|---|---|---|
| 10-19 | [day-release-20261019/README.md](day-release-20261019/README.md) | 2025/09/20 單日回放與使用流程驗收 |
| 10-18 | [regression-20261018.md](regression-20261018.md) | 網站內容優化後的完整回歸測試 |
| 10-15 | [full-audit-20261015.md](full-audit-20261015.md) | 主分支網站完整驗收與改善紀錄 |
| 10-13 | [audience-history-20261013.md](audience-history-20261013.md) | 新增一般／球隊兩種使用模式與 2025/09/20 單日分析；102 項前端測試與桌機、手機實測 |
| 10-13 | [season-context.md](season-context.md) | 單日分析的賽前狀態（連續出賽、休息天數、近期負荷）驗收 |
| 10-07 | [own-lineup-test.md](own-lineup-test.md) | 我方場上名單（選隊、配置球員／守位／棒次、套用）驗收 |
| 10-07 | [lineup-swap-test.md](lineup-swap-test.md) | 場上名單的守位與棒次互換測試 |
| 10-06 | [number-search-2025.md](number-search-2025.md) | 2025 背號搜尋功能與資料來源驗證 |
| 10-06 | [number-search-full-audit.md](number-search-full-audit.md) | 背號資料對回 360 場比賽紀錄全面複查，11,296 筆一致 |

## 使用者測試

易用性測試與預備的真人受測清單。

| 日期 | 紀錄 | 重點 |
|---|---|---|
| 10-22 | [final-closeout-20261022/USER_TASK_CHECKLIST.md](final-closeout-20261022/USER_TASK_CHECKLIST.md) | 預備給 3–5 位真人受測者的任務清單（尚未執行） |
| 10-22 | [usability-20261022/README.md](usability-20261022/README.md) | 情境式易用性測試；由代理操作，不是真人受測 |

## 簡報與發布

參賽簡報複查與推上 GitHub 前的發布檢查。

| 日期 | 紀錄 | 重點 |
|---|---|---|
| 10-22 | [submission-readiness-20261022/READINESS.md](submission-readiness-20261022/READINESS.md) | 初審提案與當時版本複查，確認 32 頁已涵蓋官方要求 |
| 10-22 | [ppt-final-audit-20261022/README.md](ppt-final-audit-20261022/README.md) | 32 頁簡報完整複查與三處文字澄清 |
| 10-22 | [cloud-update-20261022/README.md](cloud-update-20261022/README.md) | 推上 GitHub 前的驗證：84 項 Python、153 項前端測試與發布檔檢查 |
| 10-18 | [sync-20261018.md](sync-20261018.md) | 主分支整合與推送前驗收：123 項前端、60 項 Python 測試與實際操作 |
| 10-18 | [release-20261018.md](release-20261018.md) | 比賽展示與靜態發布驗收 |

## 介面

2026-10-04 起各輪前端呈現調整，僅改畫面，不改模型或分數。

| 日期 | 紀錄 | 重點 |
|---|---|---|
| 10-18 | [content-20261018.md](content-20261018.md) | 說明文字與候選比較的可讀性優化 |
| 10-18 | [light-ux-20261018.md](light-ux-20261018.md) | 預設改為淺色主題，並修正實際使用時遇到的問題 |
| 10-05 | [baseball-guidance-update.md](baseball-guidance-update.md) | 補強守位檢查、接守人選與上場資格提醒等棒球情境說明 |
| 10-05 | [readability-update-20261005.md](readability-update-20261005.md) | 文字與操作介面可讀性檢查 |
| 10-04 | [availability-baseline-update.md](availability-baseline-update.md) | 顯示今日可用名單、逐棒圖加入現任基準、四人比較卡片收合細節 |
| 10-04 | [benefit-difference-update.md](benefit-difference-update.md) | 差距圖改為以現任為 0，向右綠色較有利、向左紅色較不利 |
| 10-04 | [paired-comparison-update.md](paired-comparison-update.md) | 代打與換投候選卡共用同一張「與現任比較」圖表 |
| 10-04 | [offense-defense-alignment.md](offense-defense-alignment.md) | 代打與換投兩種評估的介面對齊 |
| 10-04 | [hitter-chart-copy-update.md](hitter-chart-copy-update.md) | 換打「優勢來源」差值圖與文字精簡 |
| 10-04 | [clarity-rules-update.md](clarity-rules-update.md) | 圖示、評估閱讀方式與棒球情境規則檢查 |
| 10-04 | [colors-availability-update.md](colors-availability-update.md) | 比較圖配色、對決字級與板凳名單檢查 |
| 10-04 | [compact-workflow-update.md](compact-workflow-update.md) | 名單摘要、手機版評估與四人比較的版面精簡 |
| 10-04 | [short-method-update.md](short-method-update.md) | 方法說明分層，預設只顯示重點、細節收合 |
| 10-04 | [user-journey-update.md](user-journey-update.md) | 從設定到比較結果實際走一遍使用流程，修正兩個問題 |
| 10-04 | [interaction-update.md](interaction-update.md) | 前端操作更新與使用流程測試 |
| 10-04 | [frontend-refinement.md](frontend-refinement.md) | 前端修改與驗證紀錄 |
| 10-04 | [typography-motion-polish.md](typography-motion-polish.md) | 字級、對齊與動態統一 |
| 10-04 | [motion-update.md](motion-update.md) | 按鍵與切換動態更新 |
| 10-04 | [rounded-surfaces-update.md](rounded-surfaces-update.md) | 卡片、按鈕與輸入框的圓角樣式統一 |
| 10-04 | [minor-polish-update.md](minor-polish-update.md) | 手機表單字級等兩處小幅一致性修正 |
