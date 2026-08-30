import json
from dataclasses import dataclass
from datetime import date, datetime

from app.deadlines import ServiceMethod
from substrate.telemetry import log_event, span

CONFIDENCE_FLOOR = 0.7

EXTRACT_INSTRUCTION = """\
You are reading a photograph of a California unlawful detainer summons.

Return ONLY a JSON object with exactly these keys:
  "case_number"    - the case number, or null if you cannot read it
  "court_branch"   - the full court name, or null
  "plaintiff_name" - the plaintiff or landlord name, or null
  "served_on"      - the date of service as YYYY-MM-DD, or null
  "service_method" - one of "personal", "substituted", "mail", or null
  "confidence"     - your confidence from 0.0 to 1.0 that you read this correctly

Never guess. A null is far better than a wrong value — someone's housing depends
on these dates being right. Do not wrap the JSON in markdown fences.
"""


@dataclass(frozen=True)
class SummonsFields:
    case_number: str | None
    court_branch: str | None
    plaintiff_name: str | None
    served_on: date | None
    service_method: ServiceMethod | None
    confidence: float


@dataclass(frozen=True)
class RetakeRequest:
    reason: str
    guidance: str


_EMPTY = SummonsFields(None, None, None, None, None, 0.0)


def _parse_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_method(value) -> ServiceMethod | None:
    try:
        return ServiceMethod(value)
    except ValueError:
        return None


def _parse_confidence(value) -> float:
    """Coerce the model's self-reported confidence, never raising.

    A confidence field that is present but not a number (a string, a list,
    anything json.loads could hand back) must not crash extraction — it is
    treated as no usable confidence, which in turn means needs_retake will
    ask for another photo rather than silently trusting an unscored read.
    """
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def extract_summons(model, image: bytes) -> SummonsFields:
    with span("navigator.extract_summons"):
        reply = model.generate(EXTRACT_INSTRUCTION, images=[image])
    try:
        payload = json.loads(reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    except json.JSONDecodeError:
        log_event("intake.unparseable", severity="WARNING")
        return _EMPTY
    if not isinstance(payload, dict):
        # Syntactically valid JSON that isn't an object -- a bare string, a
        # number, an array -- has no fields to read. Treat it the same as any
        # other malformed reply rather than crashing on `.get()`.
        log_event("intake.unparseable", severity="WARNING", reason="not_an_object")
        return _EMPTY
    return SummonsFields(
        case_number=payload.get("case_number"),
        court_branch=payload.get("court_branch"),
        plaintiff_name=payload.get("plaintiff_name"),
        served_on=_parse_date(payload.get("served_on")),
        service_method=_parse_method(payload.get("service_method")),
        confidence=_parse_confidence(payload.get("confidence")),
    )


def needs_retake(fields: SummonsFields) -> RetakeRequest | None:
    if fields.confidence < CONFIDENCE_FLOOR:
        return RetakeRequest(
            reason="low_confidence",
            guidance="Take the photo again in brighter light, holding the phone flat "
            "above the page so all four corners are visible.",
        )
    # A confident read that found neither a case number nor a court name did not
    # read a summons. This matters more than it looks: photographed with a
    # three-day notice to pay rent or quit (Cal. Code Civ. Proc. § 1161), the
    # model returns a real service date and a real service method off that
    # notice, and everything downstream then computes a § 1167 response
    # deadline -- the wrong statute, applied to a document filed before any
    # case exists -- and shows it as a countdown the tenant has no reason to
    # doubt. Only the court issues a summons, and it carries a case number and
    # the court's name; a landlord's notice carries neither. That is a
    # structural fact about the documents, so it is checked here rather than
    # asked of the model.
    if fields.case_number is None and fields.court_branch is None:
        return RetakeRequest(
            reason="not_a_summons",
            guidance="This does not look like a court summons. A summons is issued by "
            "the court and carries a case number and the court's name. If what you "
            "have is a notice from your landlord, this tool cannot work out a "
            "deadline from it -- it reads the court papers that come after. "
            "Photograph the page with the case number on it.",
        )
    if fields.served_on is None:
        return RetakeRequest(
            reason="missing_served_on",
            guidance="I could not find the date you were served. Photograph the section "
            "showing the date, or tell me the date instead.",
        )
    return None
