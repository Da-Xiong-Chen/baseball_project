# 2026 單日回放與模型檢查

本機預覽的單日分析使用 **2026/10/04** 三場例行賽，共六隊、235 個打席，含 30 次打席間換投。逐球模型在 2026/10/01 前訓練與校準。階層式估計、名單推估、球員負荷及近期配球使用 2026/10/04 前資料。資料來源為 [Rebas 2026 例行賽資料](https://github.com/rebas-tw/rebas.tw-open-data/releases/tag/v0.1.1-2026)。

- 235 打席的 470 組代打／換投視圖均和 Python 重算一致。196 筆系統提示比對沒有差異。最大數值差為 4.89 × 10⁻¹⁵。[逐筆重算](history-day-parity.json)
- 1440、390、320 CSS 像素寬度的 Chromium 實際操作涵蓋六隊選擇、打席篩選、攻守切換及實際調度揭示。測試期間沒有頁面錯誤、資料載入失敗或整頁橫向溢出。[瀏覽器結果](browser-report.json)
- 自訂換人和球隊名單使用既有 v5 批次。回放索引獨立驗證比賽、打席、提示、守位備案和配球資料，兩種批次使用各自的身分校驗。

## 模型與後續驗證

2026 全季 360 場、27,268 打席的六組近況權重比較均未達採用門檻。另在 10 月未見過的 12 場、923 打席，以相同階層式估計比較季前樹模型與 10 月月初樹模型。MSE 從 0.212573 降至 0.212028，差約 −0.000545，依比賽重抽樣的探索性區間跨零。維持現行權重。[10 月模型檢查](model-audit.json)

1. 用 2026 逐打席守位驗證接守推估，優先核對捕手、指定打擊及代打後改位。公布覆蓋率與錯判率後再決定資格規則。
2. 在多個留出月份比較誤差、校準與候選排序。按球隊與樣本量分組，核對候選接近時的名次穩定性。
3. 從兩個防守半局的牛棚模擬加入連投負荷與跨場可用量，先用歷史連戰檢查可行性與容量耗盡。

## 重現方式

使用通過進件驗證的 2024–2026 資料。將 `BASEBALL_RUNTIME_CONFIG` 指向 [2026/10/04 設定](../../../config/replay-2026-10-04.json)，並設定隔離的 `BASEBALL_DATA_ROOT` 與 `BASEBALL_MODEL_DIR`。執行 `python src/mlmodel.py 2026-10-01`，再用 `python scripts/export_single_day.py --verified-intake <進件清單> --out <輸出資料目錄>` 匯出。

將輸出目錄的上一層所產生的 `batch-context.json` 設為 `BASEBALL_BATCH_CONTEXT`，並將輸出資料目錄設為 `BASEBALL_STATIC_OUT`。以 `scripts/export_fielding_plans.py --out` 補齊當日資料夾的 `fielding-plans.json`，再執行 `tests/verify_history_day.py` 重算。日資料納入網站後，執行 `scripts/prepare_site.py` 檢查靜態發布檔案。

[32 頁簡報與 PDF](../../../presentations/competition-2026/README.md#最新工作稿)
