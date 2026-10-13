"""Update only recognizable teaching-case flow blocks, with SQLite backups."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from psm.sample_flow import HF_FLOW_ROWS, PETRO_FLOW_ROWS
from psm.enums import WIZARD_SITE_ID


ROOT = Path(__file__).resolve().parents[1]
OLD_NAMES = {
    "P-LOAD": {"密閉接收", "汽化"},
    "P-TANK": {"氣態供料"},
    "P-ACID": {"鹼液輸送管線", "氫氧化鈉水溶液"},
    "P-SCRUB": {"尾氣鹼洗"},
    "P-FEED": {"輕烴進料"},
    "P-REACT": {"HF 催化烷基化"},
    "P-PRODUCT": {"產品分離暫存"},
}


def update_case(filename: str, layouts: list[dict[str, str]]) -> None:
    path = ROOT / "data" / "demo_cases" / filename
    backup_path = path.with_name(path.stem + ".before-flow-links.sqlite")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                conn.backup(backup)
            finally:
                backup.close()
        grouped: dict[str, list[dict]] = {}
        for layout in layouts:
            grouped.setdefault(layout["process_id"], []).append(layout)
        stored: dict[str, list[tuple[int, dict]]] = {}
        for row in conn.execute(
            "SELECT row_id, payload FROM filing_row WHERE site_id=? AND section='1.3b'",
            (WIZARD_SITE_ID,),
        ):
            payload = json.loads(row["payload"])
            stored.setdefault(payload.get("process_id", ""), []).append((row["row_id"], payload))
        changed: list[str] = []
        for process_id, target in grouped.items():
            current = stored.get(process_id, [])
            names = {payload.get("name", "") for _, payload in current}
            updated_names = {layout["name"] for layout in target}
            if names and names not in (OLD_NAMES.get(process_id, set()), updated_names):
                print(f"{filename}: {process_id} has edited blocks; left unchanged")
                continue
            for row_id, _ in current:
                conn.execute("DELETE FROM filing_row WHERE row_id=?", (row_id,))
            for layout in target:
                conn.execute(
                    "INSERT INTO filing_row(site_id, section, payload) VALUES (?, '1.3b', ?)",
                    (WIZARD_SITE_ID, json.dumps(layout, ensure_ascii=False)),
                )
            changed.append(process_id)
        conn.commit()
        print(f"{filename}: linked {', '.join(changed)}; backup {backup_path.name}")
    finally:
        conn.close()


if __name__ == "__main__":
    update_case("hf-incident.sqlite", HF_FLOW_ROWS)
    update_case("petrochemical-complete.sqlite", PETRO_FLOW_ROWS)
