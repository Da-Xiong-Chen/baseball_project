# 跨年度球員 ID 資料層：實作與驗收

本階段範圍是使用現有 Rebas 2024–2025 原始資料，完成可重建、可按日期查詢的獨立身份資料層。正式網站、正式模型訓練與參賽簡報的接入不是本階段交付；完整集成模型、近期權重採用、新球季取得與多局牛棚模擬仍按原有後續規劃保留。

目前使用 `output/player-identity-20261025-v2/`。舊 v1 資料夾保留並標示已被取代。

| 原規劃要求 | 實作 | 驗收證據 |
|---|---|---|
| 來源 ID 命名空間，不按姓名／背號合併 | `players` 使用 `rebas:CPBL:<playerId>`；無效 ID 隔離，原值保存在 box JSON | 415 個 ID 全數對回原始 box；同名林子崴兩 ID 分離；無效 ID 與歧義測試通過 |
| 獨立的比賽、出場、日期化名稱、打席、逐球與來源追溯 | SQLite 的 games、player_observations、plate_appearances、pitch_events、source_files、identity_resolution_issues；名稱及球隊保留在逐場日期觀測中 | 720 場、22,630 出場觀測、54,885 打席與 206,108 球全部逐筆核對；原始檔與每個交付檔有 SHA-256 |
| 改名保持同 ID，同名保持不同 ID，跨隊觀測不失去歷史 | 6 組名稱沿革、263 個跨年 ID、17 個多隊名稱觀測 ID；不建立全域最新名稱或推定合約期間 | 核對器從原始資料重新計算所有名稱／球隊觀測，與報告完全一致 |
| 不把未來姓名、隊伍或存在性回填到歷史 | `player --as-of` 只使用指定日及之前的觀測、打席與逐球；未出現與未知 ID 同一回覆 | 全部 415 個 ID 共 2,532 組截止日查詢通過；涵蓋各姓名／隊伍首次觀測日之前及當日、跨年與資料末日 |
| 保留原始資料與問題，不猜身份或補量測 | 唯讀原始檔；歧義／缺 ID 記入問題表；四筆異常球速保留 raw JSON，數值欄為空 | 720 個來源雜湊與前次盤點一致；目前打席／逐球未解析身份 0；異常值仍為 `12+`、`122f`、空白、`14+` |
| 逐球身份必須屬於該事件實際紀錄 | 每顆球按事件姓名在同場同隊名單解析；只有欄位完全缺席才標記沿用打席名稱 | 18 顆打者、56 顆投手、26 顆捕手的名稱差異已正確解析並逐筆保留；來源逐球驗收通過 |
| 可重建且不覆寫舊成果 | 新資料夾、同路徑建置鎖、暫存建置後發布；目的地出現時拒絕替換 | 兩份完整建置的 SQLite、報告、README、manifest 四檔 SHA-256 完全相同；既有檔／鎖、失敗及另一寫入者出現的測試通過 |
| 工具、範例、報告與問題清單可交付 | 兩支 CLI、README、manifest、身份／量測／參與者差異報告、獨立全來源核對報告 | 14 項針對性測試通過；獨立核對 0 項失敗，並證明核對器可抓到總數不變的錯誤身份 |

名稱及球隊日期是觀測證據，不代表已確認的改名生效日、合約期間、轉隊日、離隊日或完整登錄名單。出場空檔不被解讀為離隊。查詢包含截止日當天全部已記錄資料，以日期為粒度，不能當成比賽當下的即時資訊。

四筆異常球速使嚴格量測 gate 保持 `false`，`model_ready` 也保持 `false`；身份資料層驗收通過不會把量測品質或模型採用一起簽認。正式載入器目前仍按既有版本運作，接入本資料層及重訓需另作正式整合、Python／JS 一致性與時間切分驗收。

## 本機使用

查詢目前驗收資料庫：

```powershell
python scripts/build_identity_continuity.py player --db output/player-identity-20261025-v2/identity.sqlite --player-id 8llux --as-of 2025-05-22
```

重新建置時必須使用未存在的新目的地：

```powershell
python scripts/build_identity_continuity.py build --seasons 2024 2025 --out output/player-identity-new
```

針對本階段測試：

```powershell
python -m unittest discover -s tests -p test_identity_continuity.py -v
```

完整來源核對與重建比較（驗收報告目的地也須不存在）：

```powershell
python scripts/verify_identity_continuity.py --artifacts output/player-identity-20261025-v2 --rebuild output/player-identity-20261025-v2-rebuild --intake output/future-work-20261025/season-intake.json --out output/player-identity-verification-20261025/new-verification.json
```

2026 原始資料目前不在本機。工具只接收明確指定且有檔案的年度；其他來源的身份不能因姓名或看似相同的 ID 自動串接。

## 保全

未 commit、push、建 PR、合併或部署。原三個未提交 QA 檔案保留；其差異 SHA-256 為 `755c80b3cce32dc8beea0f3e30f71ff1feca076777278d09712bc9a8a6f86ce4`。沒有重跑會重生正式 QA 產物的整套模型測試；本階段以 14 項行為測試及全來源逐筆核對作為驗收依據。
