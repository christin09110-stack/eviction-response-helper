import json
from pathlib import Path


def test_every_corpus_document_declares_a_citation():
    for path in Path("corpus").glob("*.md"):
        text = path.read_text()
        assert text.startswith("---"), f"{path} has no front matter"
        assert "citation:" in text, f"{path} declares no citation"


def test_form_map_covers_the_four_supported_defenses():
    spec = json.loads(Path("corpus/ud-105-fields.json").read_text())
    ids = {field["id"] for field in spec["fields"]}
    assert {
        "defense_habitability",
        "defense_retaliation",
        "defense_notice",
        "defense_rent_accepted",
    } <= ids


def test_form_map_records_where_each_field_comes_from():
    spec = json.loads(Path("corpus/ud-105-fields.json").read_text())
    assert all(field["source"] in {"summons", "user", "assessed"} for field in spec["fields"])
