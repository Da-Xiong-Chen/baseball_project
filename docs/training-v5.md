# v5 候選模型的來源固定、檢查與續跑

此入口只訓練既有 2024–2025、九個截止日的 v5 規格；不能用來宣稱 2026 模型或新的近況權重已採用。現有網站不需重訓。輸出始終放在新的 `output/` 子目錄，不覆寫 `models/`、網站資料或 active-batch。

## 1. 準備環境與原始資料

使用 Python 3.10–3.11，安裝根目錄 requirements.txt 並依資料來源文件取得兩季逐場檔及守位來源。以下從專案根目錄執行；`--data-root data` 指向包含 `rebas/2024`、`rebas/2025` 等子目錄的資料根目錄。這是實際訓練來源，不會讀取歷史 output 的 baseline 或 execution-spec。

```bash
python -m pip install -r requirements.txt
python download_data.py
```

對已有的原始資料不要直接重新下載覆寫；若來源有更新，先以新目錄進件、檢查，再產生新的來源清單。

## 2. 固定來源清單（不會訓練）

```bash
python scripts/train_identity_batch.py --prepare-source --data-root data --source-manifest output/candidate-v5/input.json
```

此命令讀取實際來源，檢查指定年度有檔案、日期年度與比賽 seq 不重複，記錄逐場 JSON 與現有守位 CSV 的 SHA-256。清單已存在時拒絕覆寫。這是來源身份檢查，不替代球員、量測、時間安全與模型效果的完整驗收。完整規格固定於 [config/training-v5.json](../config/training-v5.json)，已隨 Git 提供。

## 3. dry-run：確認來源與執行條件

```bash
python scripts/train_identity_batch.py --dry-run --data-root data --source-manifest output/candidate-v5/input.json --models output/candidate-v5/models --reports output/candidate-v5/reports
```

回傳 `validated_only`、`training_started=false`；不建立模型或訓練報告目錄，不啟動 worker。來源檔案集合、內容、程式、規格、Python 與套件版本共同識別訓練來源。任一來源檔案增加、刪除或內容變動時，必須使用新清單及新候選目錄。

## 4. 訓練候選與續跑

確認 dry-run 結果後，再移除 `--dry-run` 啟動。這是實際計算，會消耗電腦資源：

```bash
python scripts/train_identity_batch.py --data-root data --source-manifest output/candidate-v5/input.json --models output/candidate-v5/models --reports output/candidate-v5/reports --workers 6 --threads 2
```

先試單一截止日可追加 `--cutoff 2025-05-01`。完整批次會執行規格內九個截止日；最多六個 worker、每個最多四個執行緒，總上限十二執行緒。

控制器會在 reports/input-snapshot 建立經 SHA 驗證的獨立副本，每個 worker 只從此副本讀資料，啟動前與完成後都核對來源。原始資料不會被訓練程序改寫；副本、模型與報告分開保存。

中斷後先確認原控制器與 worker 已停止，檢查鎖及 `.building`／`.partial` 檔案，不要直接刪除。使用完全相同參數追加 `--resume`；只有來源識別、截止日、完成狀態與模型 SHA 都吻合才重用 checkpoint。新來源不能在舊報告目錄續跑。

## 5. 驗收與採用

產生 training-manifest 僅表示這次訓練工作完成，不代表可直接取代現有批次。後續仍需建立相容 context、以獨立暫存目錄匯出、執行時間安全／Python-JS 同情境／全季回放與模型效果驗收，再走 PR 審查及批次更新流程。[技術細節 8.4](技術細節.md#84-更新線上版的模型批次)說明目前封版與發布界線。

本次修正驗收涵蓋來源拒絕、checkpoint 行為、乾淨程式副本的 CLI 準備／dry-run、實際 724 檔的來源檢查與 worker 寫入流程的測試替身；沒有重新訓練九個正式模型，也沒有變更任何採用決策。詳見 [修正驗收](qa/review-fixes-20261029/README.md)。
