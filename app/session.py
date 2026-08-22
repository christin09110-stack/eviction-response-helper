from dataclasses import dataclass, field
from datetime import date

from app.answering import answer_question
from app.deadlines import compute_response_deadline
from app.intake import RetakeRequest, extract_summons, needs_retake
from app.preferences import preferred_style
from app.retrieval import load_corpus, retrieve
from app.safety import build_referral, check_halt
from substrate.store import Store
from substrate.telemetry import span


@dataclass
class Reply:
    kind: str
    text: str
    data: dict = field(default_factory=dict)


def _missing_service_method_retake() -> RetakeRequest:
    """A model reply can name a service method the app.deadlines.ServiceMethod
    enum does not recognise (app.intake._parse_method drops it to None rather
    than guessing at one). That reply can otherwise look entirely usable --
    high confidence, a valid served_on date -- so app.intake.needs_retake,
    which only checks confidence and served_on, lets it through. Without this
    guard, compute_response_deadline(served_on, None) raises
    ValueError("unknown service method: None") and start_case crashes instead
    of asking the user to try again. Ruling 2: never assume the model
    returned a well-shaped result.
    """
    return RetakeRequest(
        reason="missing_service_method",
        guidance="I could not tell how you were served. Photograph the section of the "
        "summons describing service, or tell me: was it handed to you directly, left "
        "with someone else, or mailed?",
    )


def start_case(model, store: Store, user_id: str, image: bytes, today: date) -> Reply:
    with span("navigator.start_case", user=user_id):
        fields = extract_summons(model, image)
        store.append_audit(user_id, {"step": "extract", "confidence": fields.confidence})

        retake = needs_retake(fields)
        if retake is None and fields.service_method is None:
            retake = _missing_service_method_retake()

        if retake is not None:
            return Reply(kind="retake", text=retake.guidance, data={"reason": retake.reason})

        deadline = compute_response_deadline(fields.served_on, fields.service_method)
        store.append_audit(user_id, {"step": "deadline", "deadline": str(deadline)})

        case = {
            "case_number": fields.case_number,
            "court_branch": fields.court_branch,
            "plaintiff_name": fields.plaintiff_name,
            "deadline": deadline,
            "facts": {},
        }

        halt = check_halt(case, today)
        if halt is not None:
            referral = build_referral(case, halt)
            store.append_audit(user_id, {"step": "halt", "reason": halt.value})
            return Reply(
                kind="halt",
                text="This needs a person, not a form. I have prepared your intake so a "
                "legal aid advocate can pick it up straight away.",
                data={"referral": referral},
            )

        store.put("cases", user_id, {**case, "deadline": str(deadline)})
        return Reply(
            kind="case_started",
            text=f"Your response is due {deadline:%A %d %B %Y}.",
            data={"deadline": str(deadline), "case_number": fields.case_number},
        )


def ask(model, store: Store, user_id: str, question: str) -> Reply:
    with span("navigator.ask", user=user_id):
        # Looked up before generation and passed into answer_question so the
        # preference actually changes what is asked of the model, not only
        # what is reported back afterwards.
        style = preferred_style(store, user_id)
        passages = retrieve(question, load_corpus())
        answer = answer_question(model, question, passages, style=style)
        store.append_audit(
            user_id,
            {"step": "answer", "grounded": answer.grounded, "citations": len(answer.citations)},
        )
        return Reply(
            kind="answer",
            text=answer.text,
            data={
                "citations": answer.citations,
                "grounded": answer.grounded,
                "style": style,
            },
        )
