# output：程式輸出與早期測試證據

這個資料夾放分析程式、回測與測試執行時寫出的結果。**評審不需要看這裡**：作品說明見 [README](../README.md)，整理過的驗收證據見 [docs/qa/](../docs/qa/README.md)。

部分檔案會被測試直接讀寫（例如 `qa/baseline/`、`qa/engine_regression.json`、`decision_v2/`），所以保留在原位置，不要搬移或改名。跑測試後若只有時間戳或換行差異，請用 `git checkout -- output/` 還原。

| 路徑 | 內容 | 產生方式 |
|---|---|---|
| `backtest_result.txt` | 每月滾動回測結果 | `src/backtest.py` |
| `ph_agreement_result.txt` | 與 2025 年教練實際代打選擇的比較 | `src/ph_agreement.py` |
| `ml_compare.txt` | 逐球結果的 8 種機器學習演算法比較 | `src/ml_compare.py` |
| `experiment.txt` | 打席開始前評估方法的完整比較 | `src/experiment.py` |
| `demo_output.txt` | 歷史回放示範輸出 | `src/demo.py` |
| `decision_v2/` | 換打／換投 v2 的一致性、重現與介面截圖證據（2026-10-03） | 見 [v2 驗收報告](../docs/archive/DECISION_V2_TEST_REPORT.md) |
| `qa/` | 首輪 QA 的資料稽核、引擎回歸基準、HTTP 回放與介面截圖（2026-10-02） | 見 [測試報告](../docs/archive/QA_TEST_REPORT.md) |
| `qa_baseline_*.txt` | 首輪 QA 修改前的測試基準 | 同上 |
| `ui/`、`ux/` | 近期配球功能與介面改版的截圖與響應式檢查（2026-10-02） | 見 [UI/UX 改版紀錄](../docs/archive/UI_UX_REFINEMENT.md) |

這些結果反映當時的版本，現行模型的數字以 [docs/技術細節.md](../docs/技術細節.md) 為準。執行時產生的大型中間檔（CSV、暫存網站、模型批次）列在 `.gitignore`，不會上傳。
