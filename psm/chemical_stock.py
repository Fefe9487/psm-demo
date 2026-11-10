"""表 1.1 的來源存量；表 1.0-4 只提供產品、SDS 與組成。"""

from __future__ import annotations

import json
import math
from collections import defaultdict

from psm import filing as fil
from psm.errors import PsmError

SECTION = "1.1-source"


def source_catalog(conn, site_id: str) -> list[dict]:
    chemicals = [dict(r) for r in conn.execute(
        """SELECT c.*, p.operating_dept_id, s.file_path AS sds_file
           FROM chemical c JOIN process p ON p.process_id=c.process_id
           LEFT JOIN sds s ON s.sds_id=c.sds_id
           WHERE p.site_id=? ORDER BY c.process_id,c.sds_id,c.cas""", (site_id,),
    )]
    groups = {}
    owned = {(c["cas"], c["process_id"], c["sds_id"]) for c in chemicals}
    for component in fil.chem_104_rows(chemicals, fil.list_rows(conn, site_id, "mix")):
        if (component["cas"], component["process_id"], component["sds_id"]) not in owned:
            continue
        kind = component["kind"]
        identity = component.get("mix_name") if kind == "混合物" else component["cas"]
        key = json.dumps([component["process_id"], component["sds_id"], kind, identity], ensure_ascii=False)
        if key not in groups:
            chem = next((c for c in chemicals if c["process_id"] == component["process_id"]
                         and c["sds_id"] == component["sds_id"] and c["cas"] == component["cas"]), {})
            groups[key] = {
                "source_key": key, "kind": kind, "process_id": component["process_id"],
                "sds_id": component["sds_id"], "cas": component["cas"] if kind == "純物質" else "",
                "name": identity if kind == "混合物" else component.get("name", ""),
                "dept_id": chem.get("operating_dept_id") or "", "components": [],
            }
        groups[key]["components"].append(component)
    return list(groups.values())


def stock_rows(conn, site_id: str) -> list[dict]:
    """未確認的舊量僅作回填參考，不混入已確認存量。"""
    stored = defaultdict(list)
    for row in fil.list_rows(conn, site_id, SECTION):
        stored[row.get("source_key")].append(row)
    result = []
    for source in source_catalog(conn, site_id):
        records = stored.get(source["source_key"], [])
        if not records:
            legacy = list(dict.fromkeys(str(c.get("total_kg")) for c in source["components"]
                                        if c.get("total_kg") not in (None, "")))
            records = [{"max_kg": legacy[0] if len(legacy) == 1 else "", "monthly_kg": "",
                        "area_code": "", "dept_id": source["dept_id"], "confirmed": False}]
        for record in records:
            result.append({**record, **source, "dept_id": record.get("dept_id") or source["dept_id"],
                           "confirmed": record.get("confirmed") is True,
                           "component_names": "、".join(c.get("name") or c["cas"] for c in source["components"])})
    return result


def _quantity(value, label: str, *, required=False) -> str:
    raw = str(value if value is not None else "").strip()
    if not raw and not required:
        return ""
    try:
        number = float(raw.replace(",", ""))
    except (ValueError, OverflowError):
        raise PsmError(f"{label}須填非負數字，單位為公斤")
    if not math.isfinite(number) or number < 0:
        raise PsmError(f"{label}須填非負數字，單位為公斤")
    return format(number, ".15g")


def save_stock(conn, site_id: str, data: dict) -> int:
    source = next((s for s in source_catalog(conn, site_id) if s["source_key"] == data.get("source_key")), None)
    if source is None:
        raise PsmError("請選表1.0-4 已建立的化學品／混合物來源")
    area, dept = str(data.get("area_code") or ""), str(data.get("dept_id") or "")
    if not conn.execute("SELECT 1 FROM area WHERE area_code=? AND site_id=?", (area, site_id)).fetchone():
        raise PsmError("存放地點須選本場所已建立的區域")
    if not conn.execute("SELECT 1 FROM department WHERE dept_id=? AND site_id=?", (dept, site_id)).fetchone():
        raise PsmError("使用單位須選本場所已建立的部門")
    maximum = _quantity(data.get("max_kg"), "最大存量", required=True)
    monthly = _quantity(data.get("monthly_kg"), "平均每月使用量")
    rows = fil.list_rows(conn, site_id, SECTION)
    raw_id = str(data.get("row_id") or "").strip()
    current = next((r for r in rows if str(r["row_id"]) == raw_id), None) if raw_id else None
    if raw_id and (current is None or current["source_key"] != source["source_key"]):
        raise PsmError("找不到這筆來源存量，或不可將既有存量改掛其他來源")
    duplicate = next((r for r in rows if r["source_key"] == source["source_key"] and r.get("area_code") == area
                      and (current is None or r["row_id"] != current["row_id"])), None)
    if current and duplicate:
        raise PsmError("此來源在該地點已有存量，請修改原紀錄，避免重複計入")
    current = current or duplicate
    payload = {k: source[k] for k in ("source_key", "kind", "process_id", "sds_id", "cas", "name")}
    payload.update(area_code=area, dept_id=dept, max_kg=maximum, monthly_kg=monthly,
                   regulation=str(data.get("regulation") or "").strip(), confirmed=True)
    if current:
        fil.update_payload(conn, current["row_id"], payload)
        return current["row_id"]
    return fil.add_row(conn, site_id, SECTION, payload)


def quantity_rows(conn, site_id: str) -> list[dict]:
    result = []
    for stock in stock_rows(conn, site_id):
        for component in stock["components"]:
            # 舊版 master 的 qty/pure_kg/formula 不可覆蓋表 1.1 的存量。
            row = {k: v for k, v in component.items() if k not in ("qty", "pure_kg", "formula")}
            row.update(total_kg=stock.get("max_kg") if stock["confirmed"] else "",
                       source_key=stock["source_key"], stock_row_id=stock.get("row_id"),
                       area_code=stock.get("area_code", ""), dept_id=stock.get("dept_id", ""),
                       stock_confirmed=stock["confirmed"], regulation=stock.get("regulation", ""))
            row = fil.attach_annex_check(row)
            row["monthly_kg"] = fil.mix_allocated(stock.get("monthly_kg", ""), row.get("pct_hi", "100"))["qty"] if stock["confirmed"] else ""
            row["formula"] = "最大存量（kg）×重量百分比（上限）÷100＝成分純物質量（kg）"
            if row["kind"] == "混合物" and row.get("basis") != "重量比":
                row.update(pure_kg="", qty="", monthly_kg="", counted=False, exceeds=False, needs_review=True,
                           annex_note="待確認：請先將成分比例換算為重量百分比（wt%）")
            if not stock["confirmed"]:
                row["annex_note"] = "待確認：請至表1.1 填寫並確認此來源的最大存量"
                row.update(counted=False, exceeds=False, needs_review=True)
            result.append(row)
    return result


def inventory_summary(conn, site_id: str) -> list[dict]:
    """依 CAS＋製程彙總各 SDS／地點的成分量，不再另收一份手填總量。"""
    groups = {}
    for component in quantity_rows(conn, site_id):
        key = (component["cas"], component["process_id"])
        if key not in groups:
            groups[key] = {"cas": key[0], "process_id": key[1], "name": component.get("name", ""),
                           "name_en": component.get("name_en", ""), "max_kg": 0.0, "monthly_kg": 0.0,
                           "max_complete": True, "monthly_complete": True, "confirmed_max_kg": 0.0,
                           "dept_ids": [], "area_codes": [], "regulations": [], "h_codes": set()}
        group = groups[key]
        maximum = fil._num(component.get("pure_kg"))
        monthly = fil._num(component.get("monthly_kg"))
        if maximum is None or not component["stock_confirmed"]:
            group["max_complete"] = False
        else:
            group["max_kg"] += maximum
        if monthly is None or not component["stock_confirmed"]:
            group["monthly_complete"] = False
        else:
            group["monthly_kg"] += monthly
        for field, value in (("dept_ids", component.get("dept_id")), ("area_codes", component.get("area_code")),
                             ("regulations", component.get("regulation"))):
            if value and value not in group[field]:
                group[field].append(value)
        group["h_codes"].update(fil.parse_h_codes(component.get("h_codes") or ""))
    for group in groups.values():
        group["confirmed_max_kg"] = f"{group['max_kg']:g}"
        group["max_kg"] = f"{group['max_kg']:g}" if group["max_complete"] else "待確認"
        group["monthly_kg"] = f"{group['monthly_kg']:g}" if group["monthly_complete"] else ""
        group["dept_id"] = "、".join(group.pop("dept_ids"))
        group["area_code"] = "、".join(group.pop("area_codes"))
        group["regulation"] = "；".join(group.pop("regulations"))
        group.update(fil.h_code_flags(",".join(group.pop("h_codes"))))
    return list(groups.values())
