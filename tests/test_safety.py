from datetime import date

from app.safety import HaltReason, build_referral, check_halt

TODAY = date(2026, 8, 12)


def test_halts_when_the_deadline_has_passed():
    facts = {"deadline": date(2026, 8, 10)}
    assert check_halt(facts, TODAY) is HaltReason.PAST_DEADLINE


def test_halts_on_a_countersuit():
    facts = {"deadline": date(2026, 8, 20), "wants_countersuit": True}
    assert check_halt(facts, TODAY) is HaltReason.COUNTERSUIT


def test_halts_on_a_habitability_injury():
    facts = {"deadline": date(2026, 8, 20), "habitability_injury": True}
    assert check_halt(facts, TODAY) is HaltReason.INJURY


def test_halts_on_a_criminal_matter():
    facts = {"deadline": date(2026, 8, 20), "criminal_matter": True}
    assert check_halt(facts, TODAY) is HaltReason.CRIMINAL


def test_no_halt_on_an_ordinary_case():
    assert check_halt({"deadline": date(2026, 8, 20)}, TODAY) is None


def test_past_deadline_outranks_other_conditions():
    facts = {"deadline": date(2026, 8, 1), "wants_countersuit": True}
    assert check_halt(facts, TODAY) is HaltReason.PAST_DEADLINE


def test_referral_carries_the_assembled_intake():
    case = {
        "case_number": "24UD001234",
        "court_branch": "Alameda",
        "plaintiff_name": "Ridgeline LLC",
        "deadline": date(2026, 8, 20),
        "facts": {"months_behind": 2},
    }
    referral = build_referral(case, HaltReason.COUNTERSUIT)
    assert referral["reason"] == "countersuit"
    assert referral["case_number"] == "24UD001234"
    assert referral["facts"] == {"months_behind": 2}
    assert referral["urgency"] == "high"


def test_past_deadline_referrals_are_marked_critical():
    case = {"case_number": "x", "deadline": date(2026, 8, 1), "facts": {}}
    assert build_referral(case, HaltReason.PAST_DEADLINE)["urgency"] == "critical"
