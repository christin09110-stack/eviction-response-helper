from substrate.store import Store
from substrate.telemetry import log_event

STYLES = ("plain", "analogy", "stepwise")
DEFAULT_STYLE = "plain"


def record_feedback(store: Store, user_id: str, style: str, landed: bool) -> None:
    if style not in STYLES:
        raise ValueError(f"unknown style: {style}")
    record = store.get("preferences", user_id) or {"scores": {}}
    scores = record["scores"]
    scores[style] = scores.get(style, 0) + (1 if landed else -1)
    store.put("preferences", user_id, {"scores": scores})
    log_event("preference.recorded", user=user_id, style=style, landed=landed)


def preferred_style(store: Store, user_id: str) -> str:
    record = store.get("preferences", user_id)
    if not record or not record.get("scores"):
        return DEFAULT_STYLE
    best = max(record["scores"].items(), key=lambda item: item[1])
    return best[0] if best[1] > 0 else DEFAULT_STYLE
