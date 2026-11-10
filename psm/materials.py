"""設備材質的逐列明細，以及舊欄位／MI 使用的顯示彙總。"""

import json

from psm.enums import MATERIAL_CATEGORIES
from psm.errors import PsmError


def normalize_rows(raw) -> list[dict]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raise PsmError("材質明細格式無效，請重新開啟設備後再填寫")
    if not isinstance(raw, list) or len(raw) > 100:
        raise PsmError("材質明細須為清單，每台設備最多 100 列")
    result, seen = [], set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise PsmError("材質明細格式無效")
        row = {key: str(item.get(key) or "").strip() for key in
               ("material_category", "material", "part", "spec", "corrosion_allowance")}
        categories = list(dict.fromkeys(value.strip() for value in row["material_category"].split(",") if value.strip()))
        if not row["material"] and not categories and not any(row[key] for key in ("part", "spec", "corrosion_allowance")):
            continue
        if not categories or any(value not in MATERIAL_CATEGORIES for value in categories):
            raise PsmError(f"第 {index} 列請先選建造材質類別")
        if not row["material"]:
            raise PsmError(f"第 {index} 列請填建造材質詳細規格名稱")
        row["material_category"] = ",".join(categories)
        signature = tuple(row.values())
        if signature in seen:
            raise PsmError(f"第 {index} 列與前面的材質明細重複")
        seen.add(signature)
        material_id = item.get("material_id")
        if material_id not in (None, ""):
            try:
                row["material_id"] = int(material_id)
            except (TypeError, ValueError):
                raise PsmError("材質明細識別碼無效")
        result.append(row)
    ids = [row["material_id"] for row in result if "material_id" in row]
    if len(set(ids)) != len(ids):
        raise PsmError("材質明細識別碼不可重複")
    return result


def rows_for_equipment(conn, equipment_id: str) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM equipment_material_detail WHERE equipment_id=? ORDER BY sort_order,material_id", (equipment_id,)
    )]


def summary(rows: list[dict]) -> dict:
    categories = list(dict.fromkeys(category for row in rows for category in row["material_category"].split(",") if category))
    return {"material_category": ",".join(categories),
            "material": "；".join((f"{row['part']}：" if row.get("part") else "") + row["material"] for row in rows),
            "spec": "；".join(dict.fromkeys(row["spec"] for row in rows if row.get("spec"))),
            "corrosion_allowance": "；".join(dict.fromkeys(row["corrosion_allowance"] for row in rows if row.get("corrosion_allowance")))}


def replace_rows(conn, equipment_id: str, rows: list[dict]) -> None:
    rows = normalize_rows(rows)
    owned = {row[0] for row in conn.execute("SELECT material_id FROM equipment_material_detail WHERE equipment_id=?", (equipment_id,))}
    supplied = {row["material_id"] for row in rows if "material_id" in row}
    if not supplied.issubset(owned):
        raise PsmError("材質明細不屬於所選設備，請重新選取設備")
    if len(rows) != 1:
        conn.execute("""UPDATE mi_inspection_detail SET confirmed=0 WHERE equipment_id=?
                        AND material_id IS NULL AND damage_mechanism<>''""", (equipment_id,))
    for material_id in owned - supplied:
        conn.execute("UPDATE mi_inspection_detail SET confirmed=0 WHERE material_id=?", (material_id,))
        conn.execute("DELETE FROM equipment_material_detail WHERE material_id=?", (material_id,))
    for order, row in enumerate(rows):
        values = tuple(row[key] for key in ("material_category", "material", "part", "spec", "corrosion_allowance"))
        if "material_id" in row:
            previous = conn.execute("SELECT material_category,material,part FROM equipment_material_detail WHERE material_id=?", (row["material_id"],)).fetchone()
            if previous and tuple(previous) != values[:3]:
                conn.execute("UPDATE mi_inspection_detail SET confirmed=0 WHERE material_id=?", (row["material_id"],))
            conn.execute("""UPDATE equipment_material_detail SET material_category=?,material=?,part=?,spec=?,
                            corrosion_allowance=?,sort_order=? WHERE material_id=? AND equipment_id=?""",
                         (*values, order, row["material_id"], equipment_id))
        else:
            conn.execute("""INSERT INTO equipment_material_detail(material_category,material,part,spec,corrosion_allowance,sort_order,equipment_id)
                            VALUES (?,?,?,?,?,?,?)""", (*values, order, equipment_id))
    bound = summary(rows)
    if rows:
        conn.execute("""INSERT INTO equipment_material(equipment_id,material_category,material,spec,corrosion_allowance)
                        VALUES (?,?,?,?,?) ON CONFLICT(equipment_id) DO UPDATE SET
                        material_category=excluded.material_category,material=excluded.material,
                        spec=excluded.spec,corrosion_allowance=excluded.corrosion_allowance""",
                     (equipment_id, bound["material_category"], bound["material"], bound["spec"], bound["corrosion_allowance"]))
    else:
        conn.execute("DELETE FROM equipment_material WHERE equipment_id=?", (equipment_id,))
    conn.execute("UPDATE equipment SET material=?,material_category=? WHERE equipment_id=?",
                 (bound["material"] or None, bound["material_category"] or None, equipment_id))


def save_rows(conn, equipment_id: str, rows) -> None:
    if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (equipment_id,)).fetchone():
        raise PsmError("設備須選已有編號")
    replace_rows(conn, equipment_id, normalize_rows(rows))
    conn.commit()
