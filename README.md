# PSMdemo

PSMdemo 是以 FastAPI 建立的製程安全資訊填報示範。這份倉庫備份包含程式、測試、專案文件、範例資料庫與必要樣本附件。

## GitHub Pages 唯讀示範

[開啟 PSM 示範網站](https://fefe9487.github.io/psm-demo/)。可切換 HF 密閉供料及石化業案例，瀏覽十四章、各製程步驟與範例報告。Pages 只提供唯讀快照；填報、附件上傳及儲存請使用下方的本機版。

發布來源為 `gh-pages` 分支根目錄，與 Python 程式及 SQLite 資料庫分開。網站只包含白名單內的 HTML、CSS 與建置檢查摘要，不會發布資料庫、歷史備份或本機附件。

重新產生及檢查網站（輸出目錄須為空）：

    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe scripts/export_pages.py --output _site
    .\.venv\Scripts\python.exe scripts/export_pages.py --output _site --check

匯出器使用兩套固定案例的暫存副本，保留原始資料庫；所有站內路徑均使用相對網址。輸出後將 `_site` 內容提交至 `gh-pages` 分支即可更新網站。目前採分支發布，`main` 更新不會自動重新匯出。

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

2026-10-19 完整測試為 **162 passed**。測試包含文件跨章引用與唯讀網站匯出；第一章流程編輯器的舊文案檢查已改為目前的控制項與「加入流程圖」文字。Pages 與文件引用修正詳見 [檢查紀錄](docs/2026-10-19-Pages與引用檢查.md)。

執行測試：

    .\.venv\Scripts\python.exe -m pytest

執行跨章資料檢查：

    .\.venv\Scripts\python.exe scripts/qa_v83.py

## 備份內容

本倉庫包含 PSMdemo 的資料庫快照。若要試填，請先另存資料庫副本，再把環境變數 PSM_WIZARD_DB_PATH（一般案例）或 PSM_WIZARD_PETRO_DB_PATH（石化案例）指向副本。
