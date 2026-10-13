"""Delete a wizard item while keeping its related records consistent."""

from __future__ import annotations

import json
import sqlite3


def delete_record(conn: sqlite3.Connection, site_id: str, table: str, where: dict[str, object], *, commit: bool = True) -> bool:
    """Delete one owned record, detaching optional references and removing dependents."""
    allowed = {
        "department", "process", "equipment", "chemical", "area", "pid_drawing",
        "training_course", "contractor_incident", "hotwork_zone",
        "unstructured_attachment", "sop", "equipment_limit",
    }
    if table not in allowed:
        raise ValueError("Unsupported item type")
    columns = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    if not where or not set(where).issubset(columns):
        raise ValueError("Invalid item key")
    clause = " AND ".join(f'"{key}"=?' for key in where)
    found = conn.execute(
        f'SELECT rowid AS _delete_rowid, * FROM "{table}" WHERE {clause}', tuple(where.values())
    ).fetchall()
    if len(found) != 1:
        return False

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    references: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {}
    nullable: dict[str, dict[str, bool]] = {}
    for child in tables:
        nullable[child] = {r[1]: not bool(r[3]) and not bool(r[5])
                           for r in conn.execute(f'PRAGMA table_info("{child}")')}
        grouped: dict[int, list] = {}
        for fk in conn.execute(f'PRAGMA foreign_key_list("{child}")'):
            grouped.setdefault(fk[0], []).append(fk)
        for parts in grouped.values():
            parent = parts[0][2]
            references.setdefault(parent, []).append(
                (child, [(p[3], p[4]) for p in sorted(parts, key=lambda p: p[1])])
            )

    removed: dict[str, set[object]] = {}
    affected_codes: set[int] = set()
    visited: set[tuple[str, int]] = set()
    conn.execute("PRAGMA defer_foreign_keys=ON")
    conn.execute("SAVEPOINT wizard_delete")
    try:
        def walk(name: str, record: sqlite3.Row) -> None:
            identity = (name, record["_delete_rowid"])
            if identity in visited:
                return
            visited.add(identity)
            identity_columns = {
                "department": "dept_id", "process": "process_id",
                "equipment": "equipment_id", "area": "area_code",
                "training_course": "course_id", "sop": "sop_id",
                "pid_drawing": "drawing_no", "design_code": "code_id",
            }
            key = identity_columns.get(name)
            if key and record[key] is not None:
                removed.setdefault(key, set()).add(record[key])
            if name == "equipment":
                affected_codes.update(r[0] for r in conn.execute(
                    "SELECT code_id FROM design_code_equipment WHERE equipment_id=?",
                    (record["equipment_id"],)
                ))
            for child, pairs in references.get(name, []):
                if not all(parent_col in record.keys() for _, parent_col in pairs):
                    continue
                condition = " AND ".join(f'"{from_col}"=?' for from_col, _ in pairs)
                values = tuple(record[parent_col] for _, parent_col in pairs)
                children = conn.execute(
                    f'SELECT rowid AS _delete_rowid, * FROM "{child}" WHERE {condition}', values
                ).fetchall()
                if all(nullable[child].get(from_col, False) for from_col, _ in pairs):
                    assignments = ", ".join(f'"{from_col}"=NULL' for from_col, _ in pairs)
                    for linked in children:
                        conn.execute(f'UPDATE "{child}" SET {assignments} WHERE rowid=?',
                                     (linked["_delete_rowid"],))
                else:
                    for linked in children:
                        walk(child, linked)
            conn.execute(f'DELETE FROM "{name}" WHERE rowid=?', (record["_delete_rowid"],))

        walk(table, found[0])
        for code_id in affected_codes:
            if conn.execute("SELECT 1 FROM design_code_equipment WHERE code_id=?", (code_id,)).fetchone():
                continue
            orphan = conn.execute("SELECT rowid AS _delete_rowid, * FROM design_code WHERE code_id=?", (code_id,)).fetchone()
            if orphan:
                walk("design_code", orphan)
        if table == "chemical":
            cas, process_id = found[0]["cas"], found[0]["process_id"]
            if not conn.execute("SELECT 1 FROM chemical WHERE cas=? AND process_id=?", (cas, process_id)).fetchone():
                cite = conn.execute("SELECT rowid AS _delete_rowid, * FROM chemical_cite WHERE cas=? AND process_id=?", (cas, process_id)).fetchone()
                if cite:
                    walk("chemical_cite", cite)
                removed.setdefault("cas_process", set()).add((cas, process_id))
        for row in conn.execute(
            "SELECT row_id, payload FROM filing_row WHERE site_id=?", (site_id,)
        ).fetchall():
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            linked_ids = payload.get("equipment_ids")
            if isinstance(linked_ids, list) and removed.get("equipment_id"):
                kept_ids = [eid for eid in linked_ids if eid not in removed["equipment_id"]]
                if len(kept_ids) != len(linked_ids):
                    if kept_ids:
                        payload["equipment_ids"] = kept_ids
                        conn.execute("UPDATE filing_row SET payload=? WHERE row_id=?",
                                     (json.dumps(payload, ensure_ascii=False), row["row_id"]))
                    else:
                        conn.execute("DELETE FROM filing_row WHERE row_id=?", (row["row_id"],))
                        continue
            affected = any(
                any(str(value) in {str(v) for v in values} for value in
                    (payload.get(key, []) if isinstance(payload.get(key), list) else [payload.get(key)]))
                for key, values in removed.items() if key != "cas_process"
            )
            if not affected and "drawing_no" in removed:
                affected = str(payload.get("pid_no")) in {str(v) for v in removed["drawing_no"]}
            if not affected and "cas_process" in removed:
                affected = (payload.get("cas"), payload.get("process_id")) in removed["cas_process"]
            if affected:
                conn.execute("DELETE FROM filing_row WHERE row_id=?", (row["row_id"],))
        conn.execute("RELEASE SAVEPOINT wizard_delete")
        if commit:
            conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT wizard_delete")
        conn.execute("RELEASE SAVEPOINT wizard_delete")
        raise
    return True
