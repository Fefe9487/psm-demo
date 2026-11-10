"""職安署公開腐蝕劣化機制總表；選項來源及擷取日期保存在資料檔。"""

import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / "data" / "damage_mechanisms.json").read_text(encoding="utf-8"))
DAMAGE_CATALOG = tuple(CATALOG["items"])
DAMAGE_BY_CODE = {row["code"]: row for row in DAMAGE_CATALOG}
DAMAGE_NAMES = tuple(row["name"] for row in DAMAGE_CATALOG)
