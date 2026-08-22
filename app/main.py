import io
import os
from datetime import date

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.forms import assess_defenses, draft_ud105
from app.intake import SummonsFields
from app.preferences import record_feedback
from app.session import ask as ask_session
from app.session import start_case
from substrate.config import load_config
from substrate.fakes import FakeFirestore
from substrate.store import Store
from substrate.telemetry import setup_telemetry
from substrate.web import create_app

_USE_FAKES = bool(os.getenv("USE_FAKE_STORE"))

config = load_config(prefix="navigator")

if _USE_FAKES:
    # setup_telemetry's default path builds a CloudTraceSpanExporter, which
    # resolves Application Default Credentials at construction time (not
    # lazily, unlike genai.Client / firestore.Client) -- calling it with no
    # span_processor here would make importing app.main require real GCP
    # credentials, which fails app.main's own module-collection for every
    # test in this suite on a machine with no ADC configured. Same
    # environment-gated seam as the Store construction below, for the same
    # reason: tests must not depend on ambient cloud credentials.
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    setup_telemetry(config, "legal-navigator", span_processor=SimpleSpanProcessor(InMemorySpanExporter()))
else:
    setup_telemetry(config, "legal-navigator")

store = Store(config, client=FakeFirestore() if _USE_FAKES else None)
app = create_app(on_event=lambda payload: None, service_name="legal-navigator")


def _model():
    # Constructed per request, not at import time: constructing it eagerly
    # at module scope would make every test collection (including ones that
    # never touch /api/case or /api/ask) pay for a Vertex client, and would
    # make USE_FAKE_STORE-style test isolation harder to reason about.
    # Ruling: models come from substrate.gemini, never a bare genai.Client
    # built inside app/.
    from substrate.gemini import GeminiModel

    return GeminiModel(config)


class AskRequest(BaseModel):
    user_id: str
    question: str


class FeedbackRequest(BaseModel):
    user_id: str
    style: str
    landed: bool


class DraftRequest(BaseModel):
    """The facts app.forms.assess_defenses consumes, gathered straight from
    the tenant -- never from the model. defendant_name is the one UD-105
    field the summons photo can't supply (source: "user" in
    corpus/ud-105-fields.json), so it is required here rather than defaulted."""

    user_id: str
    defendant_name: str
    reported_disrepair: bool = False
    landlord_notified: bool = False
    complained_on: date | None = None
    notice_served_on: date | None = None
    rent_accepted_after_notice: bool = False
    notice_defective: bool = False


@app.post("/api/case")
async def create_case(user_id: str = Form(...), photo: UploadFile = File(...)):
    image = await photo.read()
    if not image:
        raise HTTPException(status_code=422, detail="photo must not be empty")
    reply = start_case(_model(), store, user_id, image, date.today())
    return {"kind": reply.kind, "text": reply.text, "data": reply.data}


@app.post("/api/ask")
def ask_endpoint(payload: AskRequest):
    reply = ask_session(_model(), store, payload.user_id, payload.question)
    return {"kind": reply.kind, "text": reply.text, "data": reply.data}


@app.post("/api/feedback")
def feedback_endpoint(payload: FeedbackRequest):
    """Closes the loop app.session.ask() opens: the explanation style it
    returns in reply.data['style'] is worth nothing if nothing ever tells
    app.preferences whether that style landed. An unrecognised style is a
    client bug, not a server failure mode -- reported as 400, not 500."""
    try:
        record_feedback(store, payload.user_id, payload.style, landed=payload.landed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/draft")
def draft_endpoint(payload: DraftRequest):
    """Wires app.forms (implemented, deterministic, tested in
    tests/test_forms.py) into the console. Defence selection happens inside
    assess_defenses only -- the model is never called on this path.

    The PDF is rendered into an in-memory buffer (reportlab's Canvas accepts
    any file-like object, not just a path -- verified against the installed
    5.0.1) and streamed straight back, rather than written to a Cloud Run
    container's ephemeral disk or a Cloud Storage URL: nothing here needs to
    outlive the request, so there is no document to persist, and a signed
    URL would trade a same-request in-memory copy for a bucket, IAM, and a
    second network hop with no benefit to a "download and file it yourself"
    flow.
    """
    case = store.get("cases", payload.user_id)
    if case is None:
        raise HTTPException(
            status_code=404,
            detail="no case on file for this user_id -- photograph a summons first",
        )

    facts = {
        "reported_disrepair": payload.reported_disrepair,
        "landlord_notified": payload.landlord_notified,
        "complained_on": payload.complained_on,
        "notice_served_on": payload.notice_served_on,
        "rent_accepted_after_notice": payload.rent_accepted_after_notice,
        "notice_defective": payload.notice_defective,
    }
    assessments = assess_defenses(facts)
    fields = SummonsFields(
        case_number=case.get("case_number"),
        court_branch=case.get("court_branch"),
        plaintiff_name=case.get("plaintiff_name"),
        served_on=None,
        service_method=None,
        confidence=0.0,
    )

    buffer = io.BytesIO()
    draft_ud105(fields, payload.defendant_name, assessments, buffer)
    buffer.seek(0)

    store.append_audit(
        payload.user_id,
        {"step": "draft", "defenses": [a.field_id for a in assessments if a.selected]},
    )

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="UD-105-draft.pdf"'},
    )


@app.get("/")
def console():
    return FileResponse("web/index.html")


app.mount("/static", StaticFiles(directory="web"), name="static")
