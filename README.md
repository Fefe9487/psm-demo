# PSMdemo

PSMdemo 是以 FastAPI 建立的製程安全資訊填報示範。這份倉庫備份包含程式、測試、專案文件、範例資料庫與必要樣本附件。

## 啟動

在 Windows PowerShell 執行：

    py -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe run.py

服務預設在 http://127.0.0.1:8765。

## 範例資料

data/ 內保存一般版與高壓氣體版的示範／填報資料庫、示範案例和歷史資料庫備份。啟動精靈時會依選擇使用相應的填報資料庫；石化業案例資料庫位於 data/demo_cases/petrochemical-complete.sqlite。SQLite 檔案的 SHA-256 清單在 data/MANIFEST.sha256。

範例資料維持這次備份時的內容。石化業案例的 C-301 已列為高壓氣體設備，目前表 1.11 顯示待填證明；既有 T-101、R-301 證明均保留。

## 表 1.11 修正

選取「危險性機械或設備」或「高壓氣體特定設備或容器」並儲存後，該設備會出現在表 1.11。尚無證明時會顯示待填列；填報者輸入合格證號碼及有效期限。設備更名會同步更新，切換設備時不會沿用另一台設備的證號和期限。詳見 docs/2026-10-13-表1.11設備連動修正.md，畫面驗證截圖位於 docs/verification/table-1-11.png。

## PSI 相態與數量修正（2026-10-22）

表 1.1／1.2 依表 1.0-4 同步操作相態；表 1.2 將「法定門檻（kg）」與「計量判定」分開。水溶液別改為獨立確認；HCl／HF 無水液化或資料不足者顯示待確認，不再由液態直接推定為水溶液。氣體也使用 kg；體積須先換算。既有資料庫會自動新增欄位，舊液態資料須依 SDS 重新確認。詳見 [修正與驗證記錄](docs/2026-10-22-PSI相態計量與單位修正.md)。

## 驗證

驗證涵蓋管制量、相態／水溶液別、混合物更新、資料庫升級、報表與跨章關聯。測試使用獨立資料庫；既有文案檢查已依目前流程圖介面更新。

2026-10-22 驗證結果：完整測試 **169 passed**；資料庫副本外鍵與跨章關聯檢查、JavaScript 語法及 Git 差異檢查均通過。

執行測試：

    .\.venv\Scripts\python.exe -m pytest

執行跨章資料檢查：

    .\.venv\Scripts\python.exe scripts/qa_v83.py

## 備份內容

本倉庫為 PSMdemo 的私有備份，包含資料庫快照。若要試填，請先另存資料庫副本，再把環境變數 PSM_WIZARD_DB_PATH（一般案例）或 PSM_WIZARD_PETRO_DB_PATH（石化案例）指向副本。
