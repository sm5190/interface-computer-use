from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_app import db
from demo_app.app import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEGACYBANK_DB_PATH", str(tmp_path / "legacybank-test.db"))
    with TestClient(app) as test_client:
        response = test_client.post(
            "/login",
            data={"op_id": "OP100", "op_pin": "2468"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        yield test_client


def test_login_rejects_invalid_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEGACYBANK_DB_PATH", str(tmp_path / "legacybank-login-test.db"))
    with TestClient(app) as test_client:
        response = test_client.post("/login", data={"op_id": "OP100", "op_pin": "0000"})
        assert response.status_code == 401
        assert "INVALID OPERATOR ID OR PIN" in response.text


def test_search_valid_member(client: TestClient):
    response = client.post("/members/search", data={"f_14": "100001"}, follow_redirects=True)
    assert response.status_code == 200
    assert "MEMBER INQUIRY" in response.text
    assert "SAMPLE MEMBER A" in response.text


def test_profile_is_real_route(client: TestClient):
    response = client.get("/members/100001/profile")
    assert response.status_code == 200
    assert "MEMBER PROFILE" in response.text
    assert "sample.a@example.invalid" in response.text


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


def test_override_continue_and_cancel_are_functional(client: TestClient):
    response = client.get("/members/100006/accounts")
    assert "SUPERVISOR OVERRIDE REQUIRED" in response.text

    continued = client.post(
        "/members/100006/override",
        data={"decision": "continue"},
        follow_redirects=True,
    )
    assert continued.status_code == 200
    assert "SUPERVISOR OVERRIDE REQUIRED" not in continued.text
    assert "ACCOUNT SERVICING" in continued.text

    # A fresh session re-enables the injected dialog so cancel can be tested independently.
    client.post("/logout")
    client.post("/login", data={"op_id": "OP100", "op_pin": "2468"})
    cancelled = client.post(
        "/members/100006/override",
        data={"decision": "cancel"},
        follow_redirects=True,
    )
    assert cancelled.status_code == 200
    assert "MEMBER INQUIRY" in cancelled.text


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


def test_transfer_review_and_confirm_changes_balances(client: TestClient):
    accounts = db.get_accounts("100001")
    source, destination = accounts[0], accounts[1]
    source_before = source["balance"]
    destination_before = destination["balance"]

    review = client.post(
        "/members/100001/transfer/review",
        data={"from_acct": source["id"], "to_acct": destination["id"], "amount": "25.00"},
    )
    assert review.status_code == 200
    assert "REVIEW FUNDS TRANSFER" in review.text
    assert "HIGH-RISK ACTION" in review.text
    assert "F12 CONFIRM TRANSFER" in review.text

    confirmed = client.post("/members/100001/transfer/confirm")
    assert confirmed.status_code == 200
    assert "TRANSACTION COMPLETE" in confirmed.text

    source_after = db.get_account("100001", source["id"])
    destination_after = db.get_account("100001", destination["id"])
    assert source_after is not None and destination_after is not None
    assert source_after["balance"] == pytest.approx(source_before - 25.0)
    assert destination_after["balance"] == pytest.approx(destination_before + 25.0)


def test_transfer_insufficient_funds_is_validation_outcome(client: TestClient):
    accounts = db.get_accounts("100001")
    response = client.post(
        "/members/100001/transfer/review",
        data={"from_acct": accounts[0]["id"], "to_acct": accounts[1]["id"], "amount": "999999.00"},
    )
    assert response.status_code == 422
    assert "INSUFFICIENT FUNDS" in response.text


def test_withdrawal_review_and_confirm_changes_balance(client: TestClient):
    account = db.get_accounts("100002")[0]
    before = account["balance"]

    review = client.post(
        "/members/100002/withdraw/review",
        data={"from_acct": account["id"], "amount": "20.00"},
    )
    assert review.status_code == 200
    assert "REVIEW CASH WITHDRAWAL" in review.text
    assert "HIGH-RISK ACTION" in review.text
    assert "F12 CONFIRM WITHDRAWAL" in review.text

    confirmed = client.post("/members/100002/withdraw/confirm")
    assert confirmed.status_code == 200
    assert "TRANSACTION COMPLETE" in confirmed.text

    after = db.get_account("100002", account["id"])
    assert after is not None
    assert after["balance"] == pytest.approx(before - 20.0)


def test_footer_controls_are_real_controls(client: TestClient):
    response = client.get("/members")
    assert 'href="/help"' in response.text
    assert 'action="/logout"' in response.text
    assert 'onclick="legacyClear()"' in response.text


def test_logout_ends_session(client: TestClient):
    response = client.post("/logout", follow_redirects=True)
    assert response.status_code == 200
    assert "OPERATOR SIGN ON" in response.text

    protected = client.get("/members", follow_redirects=False)
    assert protected.status_code == 303


def test_templates_do_not_use_test_ids():
    template_dir = Path("demo_app/templates")
    html = "\n".join(path.read_text(encoding="utf-8") for path in template_dir.glob("*.html"))
    assert "data-testid" not in html
