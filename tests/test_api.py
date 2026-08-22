from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
