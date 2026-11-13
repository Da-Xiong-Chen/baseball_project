# 2024–2026 投打對決與三棒失分實驗

以三季中職一軍例行賽重訓。2026 年 3–10 月逐月回測，每月使用月初以前的比賽。季末離線權重用 1,080 場、82,118 個打席及 27,251 個可重建三棒視窗擬合。正式自訂評估沿用 2024–2025 v5 批次，2026 單日回放沿用原有賽前批次。

## 整體打席模型

在 27,257 個相同打席上，v5 基準 RE24 MSE 為 0.226500，時間順序集成為 0.226118，新打席結果機率模型為 0.226077，兩者各半的混合模型為 0.225626。混合相對時間順序集成改善約 0.22%，依比賽配對重抽樣的差值區間為 −0.000881 至 −0.000092。實際代打組的混合誤差點估計下降。模型以固定日期切分及固定分組追蹤，詳細區間見結果 JSON。

投打身分加入後，打席結果的 log loss 由 1.392855 降至 1.379564。額外加入球員與左右手交互作用後為 1.383185。這輪用正則化多項邏輯迴歸擬合結果機率，再用各壘況下的歷史結果 RE24 換算期望。小樣本收縮參考分層 log5 的方法。 [投打對決機率研究](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0204874)

3–6 月 13,234 席在 0.0–1.0 的權重網格選出 50:50。7–10 月 14,023 席的 MSE 為 0.223269 → 0.222851，差值 95% 區間為 −0.000962 到 +0.000094。晚局接近比分組 1,068 席為 0.213380 → 0.211090，區間 −0.003857 到 −0.000798。代打與換投後首席組的差值區間皆跨零。這是用已參與開發的 2026 資料做前後期敏感度檢驗。

## 三棒失分

依當時棒次重建後續打者，限定同一投手、連續壘況和比分，最多三打席或第三出局。失分 MSE 越低越好。共 9,050 個 2026 視窗，涵蓋 360 場。

| 方法 | 整體 | 實際換投後 1,595 筆 | 八局起分差一分內 1,453 筆 |
|---|---:|---:|---:|
| 同樣本壘況歷史平均 | 0.209104 | 0.207063 | 0.213063 |
| 同樣本局勢 Ridge | 0.209093 | 0.209515 | 0.207013 |
| 同樣本局勢與球員 Ridge | 0.210295 | 0.213748 | 0.208945 |
| 聯盟馬可夫轉移 | 0.224405 | 0.207138 | 0.234077 |
| 投手部分收縮轉移 | 0.224367 | 0.206853 | 0.233327 |
| 逐棒投打結果轉移 | 0.224533 | 0.206971 | 0.225697 |

實際換投組，投手部分收縮轉移與聯盟轉移差異的配對區間跨零。含球員 Ridge 相對局勢 Ridge 的 MSE 差在該組為 +0.004233，區間 +0.001373 至 +0.007046。同樣本序位失分模型也以只用局勢的整體 RPS 較低（0.129939 對 0.130642）。RPS 衡量整個失分機率分布的預測誤差，越低越好。因此以局勢為短期失分研究基準，正式換投排序維持目前方案。

三季內 5,497 筆未完成視窗與 3,465 筆棒次不一致的打席排除。推估名單和實際可上場名單可能不同，換投前後的候選排序檢查僅衡量排名變動。實際結果只觀察上場選手，這個比較不能判定更換某位投手會造成多少分差。 [棒球馬可夫鏈](https://pubsonline.informs.org/doi/10.1287/opre.45.1.14) · [職棒投手狀態轉移研究](https://www.jstage.jst.go.jp/article/tqs/7/2/7_69/_article/-char/en)

## 採用決定

混合模型留作整體預測候選。正式換打、換投排序維持現有版本。2026 已用於模型比較與調整，正式採用需要一段未用於開發的比賽。按既有驗收規格，整體 RE24 MSE 至少相對改善 0.1%，配對 95% 區間上限低於零，並檢查晚局接近比分、小樣本、校準及候選提示。短期模型另外看實際換投後的三棒失分與分布，並以同一候選池和同一決策時點核對排序。局勢基準可以預測該局面的失分，球員排序仍依現行評估。

## 重跑

採已核對的三季 Rebas 資料（本輪使用修正版 2025），將 BASEBALL_DATA_ROOT 設為該資料根目錄，BASEBALL_RUNTIME_CONFIG 指向[三季設定](runtime.json)。先依 [三季模型比較腳本](../../../scripts/compare_2026_same_cutoff.py) 準備同截止日 v5 及時間順序集成預測與候選比較。以下以 PowerShell 執行，每次使用新的輸出路徑。三季來源與基準須按相同球員識別規則與賽季日期重建。1,080 檔的來源清單 SHA-256 為 `deda06accc1cf89955de89b0a3fec0bae6f43f396ef7fc6b65bef7ac9128cf91`。

```powershell
$research = 'output/model-horizons-reproduction'
$comparison = 'output/verified-three-season-comparison'

$env:BASEBALL_RUNTIME_CONFIG = (Resolve-Path 'docs/qa/model-horizons-20261113/runtime.json').Path
New-Item -ItemType Directory -Path $research
python scripts/evaluate_matchup_horizons_2026.py --reference "$comparison/predictions.csv" --out "$research/horizons"
python scripts/evaluate_three_batter_calibration_2026.py --scores "$research/horizons/three-batter-scores.csv" --out "$research/calibration"
python scripts/evaluate_matchup_blend_validation_2026.py --scores "$research/horizons/pa-scores.csv" --out "$research/blend.json"
python scripts/audit_matchup_horizon_rankings_2026.py --reference "$comparison/report.json" --out "$research/rank.json"
```

[單打席與三棒結果](horizons.json) · [同樣本校準](matched-calibration.json) · [前後期檢驗](blend.json) · [候選排序摘要](rank-summary.json)。GitHub 收錄程式、測試與彙整證據。逐筆預測與研究權重留在本機研究目錄。
