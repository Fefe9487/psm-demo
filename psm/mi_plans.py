"""逐台設備、多材質、多機制的 MI 檢查明細。"""

import json

from psm import filing as fil, materials
from psm.damage_mechanisms import DAMAGE_BY_CODE, DAMAGE_NAMES
from psm.errors import PsmError


def _parse(raw, label):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raise PsmError(f"{label}格式無效，請重新開啟設備")
    if not isinstance(raw, list) or len(raw) > 200:
        raise PsmError(f"{label}須為清單，每台設備最多 200 列")
    return raw


def list_details(conn, site_id):
    result = []
    for record in conn.execute("""SELECT d.*,e.name AS equipment_name,e.equipment_type,e.process_id,e.area_code,
                                  s.mi_type,s.mi_type_confirmed FROM mi_inspection_detail d
                                  JOIN equipment e ON e.equipment_id=d.equipment_id
                                  LEFT JOIN mi_screen s ON s.equipment_id=d.equipment_id
                                  WHERE e.site_id=? ORDER BY e.process_id,e.equipment_id,d.detail_id""", (site_id,)):
        row = dict(record)
        choices = materials.rows_for_equipment(conn, row["equipment_id"])
        selected = next((m for m in choices if m["material_id"] == row["material_id"]), None)
        try:
            snapshot = json.loads(row["material_snapshot"] or "{}")
        except (ValueError, TypeError):
            snapshot = {}
        if not selected and not snapshot and row["damage_mechanism"] and len(choices) == 1:
            selected = choices[0]
        row["selected_material"] = selected or snapshot
        row["material_rows"] = [selected or snapshot] if selected or snapshot else []
        row["material"] = (selected or snapshot).get("material", "")
        row["material_category"] = (selected or snapshot).get("material_category", "")
        row["material_part"] = (selected or snapshot).get("part", "")
        row["material_missing"] = bool(snapshot and not selected)
        row["material_changed"] = bool(snapshot and selected and any(snapshot.get(key) != selected.get(key) for key in ("material", "material_category", "part")))
        result.append(row)
    return result


def save_details(conn, site_id, equipment_id, mi_type, raw_rows, raw_deleted="[]"):
    rows = _parse(raw_rows, "檢查明細")
    deleted = _parse(raw_deleted, "移除明細")
    eq = conn.execute("SELECT * FROM equipment WHERE equipment_id=? AND site_id=?", (equipment_id, site_id)).fetchone()
    if not eq:
        raise PsmError("請先選本場所已建立的設備編號")
    screen = conn.execute("SELECT is_critical FROM mi_screen WHERE equipment_id=?", (equipment_id,)).fetchone()
    if not screen or not screen["is_critical"]:
        raise PsmError("請先將設備判定為安全關鍵")
    if mi_type not in fil.MI_SIX:
        raise PsmError("請確認設備所屬的六大類")
    owned = {r[0] for r in conn.execute("SELECT detail_id FROM mi_inspection_detail WHERE equipment_id=?", (equipment_id,))}
    try:
        deleted = {int(value) for value in deleted}
    except (ValueError, TypeError):
        raise PsmError("移除明細識別碼無效")
    if not deleted.issubset(owned):
        raise PsmError("移除的檢查明細不屬於所選設備")
    if not rows and not deleted:
        raise PsmError("請新增至少一列腐蝕劣化機制或功能檢查項目")
    choices = {r["material_id"]: r for r in materials.rows_for_equipment(conn, equipment_id)}
    validated, seen_ids, signatures = [], set(), set()
    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            raise PsmError("檢查明細格式無效")
        row = {key: str(raw.get(key) or "").strip() for key in ("damage", "damage_code", "inspection_item", "method", "freq", "proc_no", "pid_no")}
        if row["damage_code"]:
            if row["damage_code"] not in DAMAGE_BY_CODE:
                raise PsmError(f"第 {index} 列的腐蝕劣化機制編號無效")
            row["damage"] = DAMAGE_BY_CODE[row["damage_code"]]["name"]
        elif row["damage"] in DAMAGE_NAMES:
            row["damage_code"] = next(code for code, item in DAMAGE_BY_CODE.items() if item["name"] == row["damage"])
        if bool(row["damage"]) == bool(row["inspection_item"]):
            raise PsmError(f"第 {index} 列須選一項腐蝕劣化機制或填一項功能檢查")
        if ("," in row["damage"] or "，" in row["damage"]) and not row["damage_code"]:
            raise PsmError(f"第 {index} 列請將多項機制分列填寫")
        if not all(row[key] for key in ("method", "freq", "proc_no", "pid_no")):
            raise PsmError(f"第 {index} 列須填檢查方式、頻率、程序書編號及 P&ID 圖號")
        if not conn.execute("SELECT 1 FROM pid_drawing WHERE drawing_no=? AND process_id=?", (row["pid_no"], eq["process_id"])).fetchone():
            raise PsmError(f"第 {index} 列 P&ID 圖號須屬於該設備的製程")
        try:
            material_id = int(raw["material_id"]) if raw.get("material_id") not in (None, "") else None
            detail_id = int(raw["detail_id"]) if raw.get("detail_id") not in (None, "") else None
        except (ValueError, TypeError):
            raise PsmError(f"第 {index} 列的明細或材質識別碼無效")
        if detail_id is not None and (detail_id not in owned or detail_id in deleted or detail_id in seen_ids):
            raise PsmError(f"第 {index} 列不屬於此設備，或明細識別碼重複")
        if detail_id is not None:
            seen_ids.add(detail_id)
        if material_id is not None and material_id not in choices:
            raise PsmError(f"第 {index} 列材質不屬於此設備，請從表1.6-1 的明細重選")
        if row["damage"] and material_id is None:
            raise PsmError(f"第 {index} 列請選適用材質；材質明細請先至表1.6-1 填寫")
        snapshot = json.dumps(choices[material_id], ensure_ascii=False) if material_id is not None else ""
        signature = (material_id, *(row[key] for key in ("damage", "inspection_item", "method", "freq", "proc_no", "pid_no")))
        if signature in signatures:
            raise PsmError(f"第 {index} 列與前面的檢查明細重複")
        signatures.add(signature)
        validated.append((detail_id, material_id, snapshot, row))
    # 所有列驗證完成後才寫入；刪除只限使用者明確移除的識別碼。
    conn.execute("SAVEPOINT mi_plan_save")
    try:
        for detail_id in deleted:
            conn.execute("DELETE FROM mi_inspection_detail WHERE detail_id=? AND equipment_id=?", (detail_id, equipment_id))
        for detail_id, material_id, snapshot, row in validated:
            values = (row["damage"], row["inspection_item"], row["method"], row["freq"], row["proc_no"], row["pid_no"], material_id, snapshot, row["damage_code"])
            if detail_id is not None:
                conn.execute("""UPDATE mi_inspection_detail SET damage_mechanism=?,inspection_item=?,inspect_method=?,
                                inspect_frequency=?,procedure_ref=?,pid_drawing_no=?,material_id=?,material_snapshot=?,
                                damage_code=?,confirmed=1 WHERE detail_id=? AND equipment_id=?""", (*values, detail_id, equipment_id))
            else:
                conn.execute("""INSERT INTO mi_inspection_detail(damage_mechanism,inspection_item,inspect_method,
                                inspect_frequency,procedure_ref,pid_drawing_no,material_id,material_snapshot,damage_code,confirmed,equipment_id)
                                VALUES (?,?,?,?,?,?,?,?,?,1,?)""", (*values, equipment_id))
        conn.execute("UPDATE mi_screen SET mi_type=?,mi_type_confirmed=1 WHERE equipment_id=?", (mi_type, equipment_id))
        conn.execute("RELEASE SAVEPOINT mi_plan_save")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT mi_plan_save")
        conn.execute("RELEASE SAVEPOINT mi_plan_save")
        raise
