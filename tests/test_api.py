from fastapi.testclient import TestClient

from app.main import app, store

client = TestClient(app)


def _seed_case(user_id: str, **overrides) -> dict:
    case = {
        "case_number": "24UD001234",
        "court_branch": "Alameda",
        "plaintiff_name": "Ridgeline LLC",
        "deadline": "2026-08-10",
        "facts": {},
    }
    case.update(overrides)
    store.put("cases", user_id, case)
    return case


def test_serves_the_mobile_console():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_case_endpoint_rejects_a_request_with_no_photo():
    assert client.post("/api/case").status_code == 422


def test_ask_endpoint_requires_a_question():
    assert client.post("/api/ask", json={"user_id": "u1"}).status_code == 422


def test_console_states_the_jurisdiction_limit():
    body = client.get("/").text.lower()
    assert "california" in body
    assert "unlawful detainer" in body


def test_console_states_that_it_does_not_file_anything():
    assert "you file it yourself" in client.get("/").text.lower()


def test_feedback_endpoint_requires_all_three_fields():
    assert client.post("/api/feedback", json={"user_id": "u1"}).status_code == 422


def test_feedback_endpoint_accepts_a_valid_style():
    response = client.post(
        "/api/feedback", json={"user_id": "u1", "style": "analogy", "landed": True}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_feedback_endpoint_rejects_an_unknown_style_with_a_client_error():
    response = client.post(
        "/api/feedback", json={"user_id": "u1", "style": "not-a-style", "landed": True}
    )
    assert response.status_code == 400


def test_case_endpoint_rejects_an_empty_photo():
    files = {"photo": ("summons.jpg", b"", "image/jpeg")}
    response = client.post("/api/case", data={"user_id": "u1"}, files=files)
    assert response.status_code == 422


def test_draft_endpoint_requires_a_case_on_file():
    response = client.post(
        "/api/draft", json={"user_id": "no-such-user", "defendant_name": "Jordan Rivera"}
    )
    assert response.status_code == 404


def test_draft_endpoint_requires_a_defendant_name():
    _seed_case("draft-missing-name")
    response = client.post("/api/draft", json={"user_id": "draft-missing-name"})
    assert response.status_code == 422


def test_draft_endpoint_returns_a_pdf_for_an_existing_case():
    _seed_case("draft-user-1")
    response = client.post(
        "/api/draft", json={"user_id": "draft-user-1", "defendant_name": "Jordan Rivera"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"


def test_draft_endpoint_offers_the_pdf_as_a_download():
    _seed_case("draft-user-2")
    response = client.post(
        "/api/draft", json={"user_id": "draft-user-2", "defendant_name": "Jordan Rivera"}
    )
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.pdf"')


def test_draft_endpoint_includes_only_the_defenses_the_submitted_facts_support():
    _seed_case("draft-user-3")
    response = client.post(
        "/api/draft",
        json={
            "user_id": "draft-user-3",
            "defendant_name": "Jordan Rivera",
            "rent_accepted_after_notice": True,
        },
    )
    assert b"Rent accepted after notice" in response.content
    assert b"Retaliatory eviction" not in response.content


def test_draft_endpoint_selects_retaliation_when_the_complaint_preceded_the_notice():
    _seed_case("draft-user-4")
    response = client.post(
        "/api/draft",
        json={
            "user_id": "draft-user-4",
            "defendant_name": "Jordan Rivera",
            "complained_on": "2026-06-01",
            "notice_served_on": "2026-07-01",
        },
    )
    assert b"Retaliatory eviction" in response.content


def test_draft_endpoint_draws_no_defenses_by_default():
    _seed_case("draft-user-5")
    response = client.post(
        "/api/draft", json={"user_id": "draft-user-5", "defendant_name": "Jordan Rivera"}
    )
    assert b"None asserted" in response.content


def test_draft_endpoint_carries_the_case_number_from_the_stored_case():
    _seed_case("draft-user-6", case_number="24UD009999")
    response = client.post(
        "/api/draft", json={"user_id": "draft-user-6", "defendant_name": "Jordan Rivera"}
    )
    assert b"24UD009999" in response.content
