from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_app.app import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEGACYBANK_DB_PATH", str(tmp_path / "legacybank-test.db"))
    with TestClient(app) as test_client:
        test_client.post("/session/start", follow_redirects=True)
        yield test_client


def test_search_valid_member(client: TestClient):
    response = client.post("/members/search", data={"f_14": "100001"}, follow_redirects=True)
    assert response.status_code == 200
    assert "MEMBER INQUIRY" in response.text
    assert "SAMPLE MEMBER A" in response.text


def test_search_unknown_member_is_business_message(client: TestClient):
    response = client.post("/members/search", data={"f_14": "999999"})
    assert response.status_code == 200
    assert "NO MEMBER FOUND" in response.text


def test_invalid_member_number_is_validation_state(client: TestClient):
    response = client.post("/members/search", data={"f_14": "abc"})
    assert response.status_code == 422
    assert "INVALID MEMBER NUMBER" in response.text


def test_normal_account_frame_contains_savings(client: TestClient):
    response = client.get("/members/100001/accounts/frame")
    assert response.status_code == 200
    assert "SAVINGS" in response.text
    assert "$8431.20" in response.text


def test_no_savings_scenario(client: TestClient):
    response = client.get("/members/100003/accounts/frame")
    assert response.status_code == 200
    assert "NO SAVINGS ACCOUNT ON FILE" in response.text


def test_permission_denied_scenario(client: TestClient):
    response = client.get("/members/100005/accounts")
    assert response.status_code == 403
    assert "SEC-403" in response.text


def test_subaccount_reaches_review_screen(client: TestClient):
    response = client.post(
        "/members/100001/accounts/new/review",
        data={
            "acct_type": "SAVINGS",
            "nick_27": "Rainy Day",
            "stmt_mode": "ELECTRONIC",
            "dep_amt": "100.00",
        },
    )
    assert response.status_code == 200
    assert "REVIEW NEW SUB-ACCOUNT" in response.text
    assert "F12 COMMIT" in response.text


def test_templates_do_not_use_test_ids():
    template_dir = Path("demo_app/templates")
    html = "\n".join(path.read_text(encoding="utf-8") for path in template_dir.glob("*.html"))
    assert "data-testid" not in html
