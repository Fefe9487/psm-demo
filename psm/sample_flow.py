"""Editable flow block layouts for the two fictional HF teaching cases."""

from __future__ import annotations


def _block(seq: int, process_id: str, name: str, desc: str = "",
           equipment_id: str = "", next_seq: int | None = None,
           next_process_id: str = "", y: int = 36,
           branch_from: int | None = None) -> dict[str, str]:
    return {
        "seq": str(seq), "process_id": process_id, "name": name,
        "desc": desc, "equipment_id": equipment_id,
        "next": str(next_seq) if next_seq is not None else "",
        "next_process_id": next_process_id,
        "branch_from": str(branch_from) if branch_from is not None else "",
        "x": str(24 + (seq - 1) * 220 if y == 36 else 24),
        "y": str(y),
    }


HF_FLOW_ROWS = [
    _block(1, "P-LOAD", "密閉接收", "液態無水 HF 經密閉接頭接入汽化模組", "LA-101", 2),
    _block(2, "P-LOAD", "汽化", "V-101 汽化後進入 HF 供料段", "V-101", next_process_id="P-TANK"),
    _block(1, "P-TANK", "HF 緩衝", "T-101 緩衝氣態 HF", "T-101", 2),
    _block(2, "P-TANK", "密閉供料", "P-101 向用料端密閉供氣", "P-101"),
    _block(3, "P-TANK", "含氟尾氣收集", "供料段含氟尾氣另行收集，送鹼洗段", next_process_id="P-SCRUB", y=430, branch_from=2),
    _block(1, "P-ACID", "氫氧化鈉水溶液", "10% 氫氧化鈉水溶液供鹼洗使用", next_seq=2),
    _block(2, "P-ACID", "鹼液輸送管線", "PL-201 輸送鹼液至尾氣鹼洗塔", "PL-201", next_process_id="P-SCRUB"),
    _block(1, "P-SCRUB", "尾氣鹼洗", "S-201 使用 10% NaOH 水溶液吸收含氟尾氣", "S-201"),
]


PETRO_FLOW_ROWS = [
    *[
        {**row, "next_process_id": "P-REACT"}
        if row["process_id"] == "P-TANK" and row["seq"] == "2" else dict(row)
        for row in HF_FLOW_ROWS
    ],
    _block(1, "P-FEED", "輕烴進料緩衝", "異丁烷與丁烯密閉進料", "V-301", 2),
    _block(2, "P-FEED", "輕烴進料輸送", "P-301 將進料送至反應段", "P-301", next_process_id="P-REACT"),
    _block(1, "P-REACT", "HF 催化烷基化", "R-301 反應後產物流向分離段；HF 催化劑密閉循環", "R-301", next_process_id="P-PRODUCT"),
    _block(2, "P-REACT", "含氟尾氣收集", "反應段含氟尾氣另行收集，送鹼洗段", next_process_id="P-SCRUB", y=430, branch_from=1),
    _block(1, "P-PRODUCT", "產品分離", "C-301 分離反應產物", "C-301", 2),
    _block(2, "P-PRODUCT", "產品暫存", "T-301 密閉暫存烷基化油", "T-301"),
]
