"""Equipment flags must drive table 1.11 and its completion checks."""

import re

import pytest
from fastapi.testclient import TestClient

from psm import db, filing as fil, wizard
from psm.enums import WIZARD_SITE_ID
from psm.web import app


def _client(tmp_path, monkeypatch):
    path = tmp_path / "legal.sqlite"
    for module in ("psm.db", "psm.web", "psm.wizard"):
        monkeypatch.setattr(module + ".db_path", lambda: path)
    client = TestClient(app)
    client.post("/wizard/defaults", data={"step": "1"})
    return client, path


def _equipment(**flags):
    return {
        "equipment_id": "V-LEGAL", "name": "測試設備",
        "process_id": "P-TANK", "maint_dept_id": "D-MAINT",
        "equipment_type": "壓力容器與儲槽", "phase_class": "氣體",
        "legal_cert_type": "既有備註，不是證號",
        **flags,
    }


def _certificate(**fields):
    return {
        "step": "1", "section": "1.11", "equipment_id": "V-LEGAL",
        "category": "高壓氣體特定設備", "cert_no": "TEST-CERT-001",
        "expire": "2027-12-31", **fields,
    }


def _select(html):
    return re.search(r'<select[^>]*id="psi-111-eq"[^>]*>(.*?)</select>', html, re.S).group(1)


@pytest.mark.parametrize("flags,category", [
    ({"is_regulated_machinery": "on"}, "危險性機械或設備"),
    ({"is_high_pressure_gas": "on"}, "高壓氣體特定設備或容器"),
    ({"is_regulated_machinery": "on", "is_high_pressure_gas": "on"}, "危險性機械或設備／高壓氣體特定設備或容器"),
])
def test_each_equipment_flag_creates_pending_reference(tmp_path, monkeypatch, flags, category):
    client, path = _client(tmp_path, monkeypatch)
    response = client.post("/wizard/1/equipment", data=_equipment(**flags), headers={"X-PSM-Partial": "1"})
    assert response.json()["ok"]
    for flag in flags:
        assert response.json()["row"][flag] == "on"
    html = client.get("/wizard/1").text
    master = re.search(r'<tr data-edit="equipment" data-json="([^"]*V-LEGAL[^"]*)"', html)
    assert master
    for flag in flags:
        assert f'&#34;{flag}&#34;: 1' in master.group(1)
    options = _select(html)
    assert options.count('value="V-LEGAL"') == 1
    assert f'data-category="{category}"' in options
    assert 'value="P-101"' not in options
    assert "data-cert=" not in options
    pending = html.split('<tbody id="psi-111-pending">')[1].split("</tbody>")[0]
    assert "V-LEGAL" in pending and "填寫證明" in pending
    with db.connect(path) as conn:
        assert not any(r.get("equipment_id") == "V-LEGAL" for r in fil.list_rows(conn, WIZARD_SITE_ID, "1.11"))
        assert any("V-LEGAL" in gap for gap in wizard.step_missing(conn, WIZARD_SITE_ID, 1))
    saved = client.post("/wizard/row", data=_certificate(), follow_redirects=False)
    assert "err=" not in saved.headers["location"]
    with db.connect(path) as conn:
        assert not wizard.legal_certificate_gaps(conn, WIZARD_SITE_ID)
    pending = client.get("/wizard/1").text.split('<tbody id="psi-111-pending">')[1].split("</tbody>")[0]
    assert "V-LEGAL" not in pending


@pytest.mark.parametrize("fields", [
    {"equipment_id": "P-101"}, {"equipment_id": "UNKNOWN"},
    {"category": " "}, {"cert_no": ""}, {"expire": ""}, {"expire": "2027-02-31"},
])
def test_certificate_rejects_ineligible_or_incomplete_input(tmp_path, monkeypatch, fields):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/1/equipment", data=_equipment(is_high_pressure_gas="on"))
    with db.connect(path) as conn:
        before = fil.list_rows(conn, WIZARD_SITE_ID, "1.11")
    response = client.post("/wizard/row", data=_certificate(**fields), follow_redirects=False)
    assert "err=" in response.headers["location"]
    with db.connect(path) as conn:
        assert fil.list_rows(conn, WIZARD_SITE_ID, "1.11") == before


def test_rename_and_unflag_keep_certificate_and_check_relationship(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/1/equipment", data=_equipment(is_high_pressure_gas="on"))
    client.post("/wizard/row", data=_certificate())
    with db.connect(path) as conn:
        cert = next(r for r in fil.list_rows(conn, WIZARD_SITE_ID, "1.11") if r["equipment_id"] == "V-LEGAL")
    renamed = _equipment(is_regulated_machinery="on", is_high_pressure_gas="on")
    renamed["name"] = "更名後設備"
    client.post("/wizard/1/equipment", data=renamed)
    html = client.get("/wizard/1").text
    assert 'data-legal-name="V-LEGAL">更名後設備' in html
    updated = client.post("/wizard/row", data=_certificate(row_id=cert["row_id"], cert_no="UPDATED-CERT"), follow_redirects=False)
    assert "err=" not in updated.headers["location"]
    client.post("/wizard/1/equipment", data=_equipment())
    assert 'value="V-LEGAL"' not in _select(client.get("/wizard/1").text)
    with db.connect(path) as conn:
        rows = fil.list_rows(conn, WIZARD_SITE_ID, "1.11")
        assert any(r.get("cert_no") == "UPDATED-CERT" for r in rows)
        assert any("V-LEGAL" in gap and "確認關聯" in gap for gap in wizard.legal_certificate_gaps(conn, WIZARD_SITE_ID))


def test_no_equipment_declaration_cannot_bypass_flagged_devices(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    rejected = client.post("/wizard/flags", data={"step": "1", "no_art16": "1"}, follow_redirects=False)
    assert "err=" in rejected.headers["location"]
    with db.connect(path) as conn:
        fil.set_flag(conn, WIZARD_SITE_ID, "no_art16", "1")
        assert wizard.legal_certificate_gaps(conn, WIZARD_SITE_ID)
        conn.execute("UPDATE equipment SET is_regulated_machinery=0,is_high_pressure_gas=0")
        conn.execute("DELETE FROM filing_row WHERE section='1.11'")
        conn.commit()
        assert not wizard.legal_certificate_gaps(conn, WIZARD_SITE_ID)
    client.post("/wizard/1/equipment", data=_equipment(is_high_pressure_gas="on"))
    with db.connect(path) as conn:
        assert fil.get_flag(conn, WIZARD_SITE_ID, "no_art16") == "0"
        assert any("V-LEGAL" in gap for gap in wizard.legal_certificate_gaps(conn, WIZARD_SITE_ID))


def test_incomplete_legacy_row_does_not_complete_flagged_device(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/1/equipment", data=_equipment(is_high_pressure_gas="on"))
    with db.connect(path) as conn:
        fil.add_row(conn, WIZARD_SITE_ID, "1.11", {"equipment_id": "V-LEGAL", "category": "高壓氣體"})
        assert any("V-LEGAL" in gap for gap in wizard.legal_certificate_gaps(conn, WIZARD_SITE_ID))
