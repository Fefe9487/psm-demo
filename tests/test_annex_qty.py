"""勞動檢查法施行細則（FL015074）規定數量：操作量×wt%＝純物質。"""

from __future__ import annotations

from psm.db import connect, init_schema
from psm.enums import SITE_ID
from psm.filing import annex_catalog, annex_fill_blanks, annex_qty_check, attach_annex_check, lookup_annex, merge_annex_qty
from psm.seed import seed_demo
from psm.services import generate_report_html


def test_h2o2_mixture_exceeds_annex1_limit():
    r = annex_qty_check(cas="7722-84-1", op_kg="20000", wt_pct="35")
    assert r["listed"] is True
    assert r["annex"] == "危險物"
    assert r["limit_kg"] == 5000
    assert r["pure_kg"] == 7000
    assert r["counted"] is True
    assert r["exceeds"] is True


def test_toluene_not_on_annex_tables():
    r = annex_qty_check(cas="108-88-3", op_kg="50000", wt_pct="100")
    assert r["listed"] is False
    assert r["counted"] is False
    assert r["exceeds"] is False
    assert r["pure_kg"] == 50000
    assert "未列" in r["note"]


def test_hcl_aqueous_excluded_gas_counted():
    aq = annex_qty_check(cas="7647-01-0", op_kg="20000", wt_pct="35", is_aqueous=True)
    assert aq["listed"] is True
    assert aq["limit_kg"] == 5000
    assert aq["pure_kg"] == 7000
    assert aq["counted"] is False
    assert aq["exceeds"] is False
    assert "水溶液" in aq["note"]
    gas = annex_qty_check(cas="7647-01-0", op_kg="6000", wt_pct="100", is_aqueous=False)
    assert gas["counted"] is True
    assert gas["exceeds"] is True


def test_hcl_liquid_phase_excluded_gas_phase_counted():
    liq = annex_qty_check(cas="7647-01-0", op_kg="20000", wt_pct="35", phase="液態")
    assert liq["listed"] is True
    assert liq["limit_phase"] == "氣態"
    assert liq["counted"] is False
    assert "相態不符" in liq["note"]
    gas = annex_qty_check(cas="7647-01-0", op_kg="6000", wt_pct="100", phase="氣態")
    assert gas["counted"] is True
    assert gas["exceeds"] is True


def test_ungated_phase_still_counts():
    r = annex_qty_check(cas="7722-84-1", op_kg="20000", wt_pct="35", phase="氣態")
    assert r["limit_phase"] == "液態"
    assert r["counted"] is True
    assert r["exceeds"] is True


def test_hf_aqueous_excluded():
    r = annex_qty_check(cas="7664-39-3", op_kg="2000", wt_pct="50", is_aqueous=True)
    assert r["listed"] is True
    assert r["counted"] is False


def test_nitrocellulose_needs_nitrogen_above_12_6():
    low = annex_qty_check(cas="9004-70-0", op_kg="20000", wt_pct="100", n_pct="12.0")
    assert low["counted"] is False
    hi = annex_qty_check(cas="9004-70-0", op_kg="20000", wt_pct="100", n_pct="12.7")
    assert hi["counted"] is True
    assert hi["exceeds"] is True
    assert hi["limit_kg"] == 10000


def test_range_uses_upper_wt():
    r = annex_qty_check(cas="75-56-9", op_kg="12000", wt_pct="99", wt_lo="90")
    assert r["pure_kg"] == 11880
    assert r["limit_kg"] == 10000
    assert r["exceeds"] is True
    assert r["estimate"] is True


def test_merge_same_cas_within_site():
    rows = [
        attach_annex_check(
            {"cas": "75-21-8", "total_kg": "3000", "pct_hi": "100", "process_id": "P-A"}
        ),
        attach_annex_check(
            {"cas": "75-21-8", "total_kg": "2500", "pct_hi": "100", "process_id": "P-B"}
        ),
    ]
    merged = merge_annex_qty(rows)
    one = merged["75-21-8"]
    assert one["pure_kg"] == 5500
    assert one["limit_kg"] == 5000
    assert one["exceeds"] is True
    assert lookup_annex("75-21-8")["name_zh"] == "環氧乙烷"


def test_seeded_demo_shows_pure_qty_and_reaction_heat():
    conn = connect(":memory:")
    init_schema(conn)
    seed_demo(conn)
    html = generate_report_html(conn, SITE_ID)
    assert "7722-84-1" in html
    assert "純物質" in html
    assert "規定數量" in html
    assert "7000" in html or "7,000" in html
    assert "達規定數量" in html
    assert "2 H2O2" in html or "H2O2" in html
    assert "反應熱" in html
    assert "−98" in html or "-98" in html
    h2o2 = conn.execute(
        "SELECT 1 FROM chemical WHERE cas='7722-84-1' AND process_id='P-SCRUB'"
    ).fetchone()
    assert h2o2
    rxn = conn.execute(
        "SELECT * FROM reaction_info WHERE process_id='P-SCRUB'"
    ).fetchone()
    assert rxn["heat"]
    assert conn.execute(
        "SELECT has_chemical_reaction FROM process WHERE process_id='P-SCRUB'"
    ).fetchone()[0]


def test_annex_catalog_has_cas_and_skips_blank():
    rows = annex_catalog()
    assert rows
    assert all(r["cas"] for r in rows)
    assert any(r["cas"] == "7722-84-1" for r in rows)
    assert not any(r["cas"] == "108-88-3" for r in rows)


def test_annex_fill_blanks_only_listed_and_empty_fields():
    listed = annex_fill_blanks("7722-84-1", {"cas": "7722-84-1", "name": ""}, keys=("name", "name_en", "ctrl_qty"))
    assert listed["name"] == "過氧化氫"
    assert listed["name_en"] == "Hydrogen peroxide"
    assert listed["ctrl_qty"] == "5000"
    keep = annex_fill_blanks(
        "7722-84-1",
        {"cas": "7722-84-1", "name": "現場自訂名"},
        keys=("name",),
    )
    assert keep["name"] == "現場自訂名"
    other = annex_fill_blanks("108-88-3", {"cas": "108-88-3", "name": ""}, keys=("name", "ctrl_qty"))
    assert other["name"] == ""
    assert "ctrl_qty" not in other or not other.get("ctrl_qty")
