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

## 驗證

本次連動相關測試為 19 passed。完整測試目前有 155 個通過、1 個既有文案檢查失敗：test_psi_handbook_tables_on_step1 仍期待舊按鈕文字「建立方塊」，目前介面文案為「加入流程圖」。修正記錄說明了測試範圍。

執行測試：

    .\.venv\Scripts\python.exe -m pytest

執行跨章資料檢查：

    .\.venv\Scripts\python.exe scripts/qa_v83.py

## 備份內容

本倉庫為 PSMdemo 的私有備份，包含資料庫快照。若要試填，請先另存資料庫副本，再把環境變數 PSM_WIZARD_DB_PATH（一般案例）或 PSM_WIZARD_PETRO_DB_PATH（石化案例）指向副本。