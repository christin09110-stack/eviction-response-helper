from datetime import date
from enum import Enum

from app.deadlines import days_remaining
from substrate.telemetry import log_event


class HaltReason(str, Enum):
    PAST_DEADLINE = "past_deadline"
    COUNTERSUIT = "countersuit"
    INJURY = "injury"
    CRIMINAL = "criminal"


def check_halt(facts: dict, today: date) -> HaltReason | None:
    """Ordered by severity — a missed deadline outranks everything else."""
    deadline = facts.get("deadline")
    if deadline and days_remaining(deadline, today) < 0:
        return HaltReason.PAST_DEADLINE
    if facts.get("wants_countersuit"):
        return HaltReason.COUNTERSUIT
    if facts.get("habitability_injury"):
        return HaltReason.INJURY
    if facts.get("criminal_matter"):
        return HaltReason.CRIMINAL
    return None


def build_referral(case: dict, reason: HaltReason) -> dict:
    """Assemble the intake a legal-aid organisation would otherwise gather by hand."""
    log_event("safety.halt", reason=reason.value, case=case.get("case_number"))
    return {
        "reason": reason.value,
        "urgency": "critical" if reason is HaltReason.PAST_DEADLINE else "high",
        "case_number": case.get("case_number"),
        "court_branch": case.get("court_branch"),
        "plaintiff_name": case.get("plaintiff_name"),
        "deadline": str(case.get("deadline")) if case.get("deadline") else None,
        "facts": case.get("facts", {}),
        "note": "Prepared by an automated navigator. All facts are as reported by the "
        "tenant and are unverified.",
    }
