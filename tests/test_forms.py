from datetime import date
from pathlib import Path

from app.deadlines import ServiceMethod
from app.forms import DefenseAssessment, assess_defenses, draft_ud105
from app.intake import SummonsFields

FIELDS = SummonsFields(
    "24UD001234", "Alameda", "Ridgeline LLC", date(2026, 8, 3), ServiceMethod.PERSONAL, 0.95
)


def _selected(assessments):
    return {a.field_id for a in assessments if a.selected}


def test_no_defenses_selected_when_no_facts_support_them():
    assert _selected(assess_defenses({})) == set()


def test_habitability_selected_when_disrepair_was_reported():
    facts = {"reported_disrepair": True, "landlord_notified": True}
    assessments = assess_defenses(facts)
    assert "defense_habitability" in _selected(assessments)


def test_habitability_not_selected_when_landlord_was_never_told():
    facts = {"reported_disrepair": True, "landlord_notified": False}
    assert "defense_habitability" not in _selected(assess_defenses(facts))


def test_retaliation_selected_when_complaint_preceded_notice():
    facts = {"complained_on": date(2026, 6, 1), "notice_served_on": date(2026, 7, 1)}
    assert "defense_retaliation" in _selected(assess_defenses(facts))


def test_retaliation_not_selected_when_complaint_came_after_notice():
    facts = {"complained_on": date(2026, 7, 15), "notice_served_on": date(2026, 7, 1)}
    assert "defense_retaliation" not in _selected(assess_defenses(facts))


def test_rent_accepted_selected_when_payment_taken_after_notice():
    facts = {"rent_accepted_after_notice": True}
    assert "defense_rent_accepted" in _selected(assess_defenses(facts))


def test_every_selected_defense_records_its_basis():
    facts = {"reported_disrepair": True, "landlord_notified": True}
    for assessment in assess_defenses(facts):
        if assessment.selected:
            assert assessment.basis, "a selected defence must record why"


def test_assessments_are_returned_for_every_form_defense_field():
    assert len(assess_defenses({})) == 4


def test_draft_writes_a_pdf_containing_the_case_number(tmp_path: Path):
    out = str(tmp_path / "ud105.pdf")
    path = draft_ud105(FIELDS, "Jordan Rivera", assess_defenses({}), out)
    assert Path(path).exists()
    assert Path(path).read_bytes()[:5] == b"%PDF-"


def test_draft_includes_only_the_selected_defenses(tmp_path: Path):
    facts = {"rent_accepted_after_notice": True}
    out = str(tmp_path / "ud105.pdf")
    draft_ud105(FIELDS, "Jordan Rivera", assess_defenses(facts), out)
    text = Path(out).read_bytes()
    assert b"Rent accepted after notice" in text
    assert b"Retaliatory eviction" not in text
