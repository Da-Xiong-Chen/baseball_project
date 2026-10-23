# 最新版本與更新保留核對

核對日期：2026-10-03（臺北）。

## 遠端版本

- 已另行 clone `https://github.com/Da-Xiong-Chen/baseball_project.git` 到 `D:\資料集_CIC_IDS\資訊服務競賽\baseball_project_latest`，原工作目錄完整保留。
- 最新 clone 的 `origin/main`：`a3b8636e5568fc7acb04e676d210ba0d5447ed16`，與本次功能修改的共同基線一致；此次核對時沒有新增的上游主分支提交。
- 原本功能分支基線：`3aa9589d353383039a6cc4400570bba6e4580a19`，包含先前近期配球功能及 PR 紀錄。
- PR #1 於核對時仍開啟、尚未合併：[原作者審查入口](https://github.com/Da-Xiong-Chen/baseball_project/pull/1)。因此單獨 clone 上游 `main` 不會自動取得本次功能。

## 保留方式與驗證

修改前備份位於原專案 `output/decision_v2/pre-sync-local.zip`，339 個檔案已逐一驗證 SHA-256；另存 tracked patch 與 manifest。備份不提交 Git。

本次使用 Git 提交保存完整功能分支，再將該分支帶入最新 clone；保留先前功能提交的歷史，避免只套用最後一輪 diff 而遺失近期配球功能。整合完成結果、兩份 checkout 的提交及檔案核對另記錄於 `output/decision_v2/sync-verification.json`。

核對結果：功能提交 `40671b4ce8e94aab7065301294f062c296df8d22` 已成功 push 到既有 fork 分支。最新 clone 再從 GitHub fetch，確認遠端功能 SHA 與本機相同；562 個已追蹤檔案內容一致（文字僅正規化 CRLF／LF），Git tree 相同，最新上游主分支是功能提交的祖先。clone 中再次通過 29 項 Python、24 項 JavaScript、18 組一致性及 498 情境核對、八組已存介面證據檢查。

PR 標題與說明已更新為完整換打／換投範圍。GitHub connector 編輯遭 403 權限限制後，改用已登入的 GitHub 網頁完成，並確認新說明已保存；畫面證據為 `output/decision_v2/ui/pr-updated.png`。PR 保持開啟，由原作者審查合併。本核對紀錄以功能提交為基準，後續僅補交付文件及證據。

核心更新包含深淺主題、換打／換投候選比較、模型分歧與資料提示、截止日期修正、v2 模型參數及完整回放，以及 README 期刊依據和測試文件。原始逐球資料、非公開守位資料、模型 pickle、隔離環境均不提交。

## 驗收範圍

29 項 Python、24 項 JavaScript、18 組計算一致性、275 場／498 情境回放及介面操作證據見 [v2 報告](DECISION_V2_TEST_REPORT.md)。全新環境重下載公開資料、重訓 9 個模型，277 個匯出 JSON 完全一致。

這次工程交付保留真人、實體手機、獨立瀏覽器及部分無障礙驗收待完成狀態；不宣稱已公開部署或已由原作者合併。原專案仍供 `http://127.0.0.1:8011/` 本機預覽使用。
