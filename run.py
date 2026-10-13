"""本機啟動：python run.py  →  http://127.0.0.1:8765"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("psm.web:app", host="127.0.0.1", port=8765, reload=True)
