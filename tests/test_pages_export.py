"""Integration checks for the portable, inert static snapshot."""

import hashlib

import pytest
from bs4 import BeautifulSoup

from scripts.export_pages import CASES, ROOT, export_site, transform, validate_site


def test_export_keeps_cases_separate_and_never_changes_databases(tmp_path):
    paths = [ROOT / "data/demo_cases" / name for _, name in CASES.values()]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    site = tmp_path / "public"
    result = export_site(site)
    assert result["pages"] >= 31
    assert result["local_references_checked"] > 1000
    for case in CASES:
        for chapter in range(1, 15):
            text = (site / f"{case}/wizard/{chapter}.html").read_text(encoding="utf-8")
            assert "唯讀示範" in text
            assert f"第 {chapter} 章" in text
    hf = BeautifulSoup((site / "hf/report.html").read_text(encoding="utf-8"), "html.parser")
    petro = BeautifulSoup((site / "petrochemical/report.html").read_text(encoding="utf-8"), "html.parser")
    assert "HF 密閉供料" in hf.h1.get_text()
    assert "HF 催化烷基化" in petro.h1.get_text()
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before


@pytest.mark.parametrize("reference", ["/static/missing.css", "../outside.html", "#absent"])
def test_broken_or_escaping_references_fail_validation(tmp_path, reference):
    (tmp_path / "index.html").write_text(f'<a href="{reference}">broken</a>', encoding="utf-8")
    with pytest.raises(ValueError):
        validate_site(tmp_path)


def test_static_fields_remain_visible_without_javascript():
    source = '<html><head></head><body><label data-panel="selected" hidden><input value="saved" onchange="submit()"></label><form action="/save" method="post"><button>儲存</button></form><script>fetch("/save")</script></body></html>'
    text = transform(source, "hf", "hf/wizard/2.html", [])
    assert 'value="saved"' in text
    assert "hidden" not in text
    assert "onchange" not in text
    assert "<script" not in text
    assert "<form" not in text
    assert "<button" not in text
