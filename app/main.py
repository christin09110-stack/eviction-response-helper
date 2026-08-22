import os
from datetime import date

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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


@app.get("/")
def console():
    return FileResponse("web/index.html")


app.mount("/static", StaticFiles(directory="web"), name="static")
