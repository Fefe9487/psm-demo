# PSMdemo

PSMdemo 是以 FastAPI 建立的製程安全資訊填報示範。這份倉庫備份包含程式、測試、專案文件、範例資料庫與必要樣本附件。

## GitHub Pages 互動展示

[開啟 PSM 互動展示](https://fefe9487.github.io/psm-demo/)。可切換 HF 密閉供料及石化業案例，使用原本的十四章填報介面：新增、修改、刪除資料、編輯流程圖、上傳附件、儲存及產生報告。頁面上方可恢復目前案例的預設資料。

原 FastAPI 與 SQLite 透過 Pyodide 在瀏覽器內執行，Service Worker 處理網站自己的 `/app/` 請求。每位訪客的修改與附件保存在自己的 IndexedDB；其他訪客不會看到，清除網站資料會恢復預設。第一次啟動需下載約 19 MB 系統檔案，之後使用瀏覽器快取。展示不含多人共享或跨裝置同步。

重新建置網站（輸出目錄須為空）：

    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe scripts/build_browser_demo.py --output _site

建置器下載固定版本的官方 Pyodide 執行環境與 Python wheels，驗證套件雜湊，並打包程式、樣式及三個指定範例資料庫；不包含歷史備份或本機上傳檔案。執行環境與套件均隨網站發布，訪客不需連接 PyPI 或 CDN。將 `_site` 內容提交至 `gh-pages` 分支即可更新網站；`main` 更新不會自動建置。舊的靜態快照匯出器仍可另行產生離線參考資料，網站首頁使用互動版。

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

2026-10-19 完整測試為 **168 passed**。測試包含文件跨章引用、瀏覽器轉接層的儲存／上傳／還原、兩套案例的十四章路由、網址改寫與 JavaScript 語法。Pages 與文件引用修正詳見 [檢查紀錄](docs/2026-10-19-Pages與引用檢查.md)。

執行測試：

    .\.venv\Scripts\python.exe -m pytest

執行跨章資料檢查：

    .\.venv\Scripts\python.exe scripts/qa_v83.py

## 備份內容

本倉庫包含 PSMdemo 的資料庫快照。若要試填，請先另存資料庫副本，再把環境變數 PSM_WIZARD_DB_PATH（一般案例）或 PSM_WIZARD_PETRO_DB_PATH（石化案例）指向副本。
