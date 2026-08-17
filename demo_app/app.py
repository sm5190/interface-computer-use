from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .fixtures import OPERATORS
from .scenarios import consume_slow_once

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="LegacyBank Operations Console", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("LEGACYBANK_SESSION_SECRET", "legacybank-dev-secret"),
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def require_session(request: Request) -> RedirectResponse | None:
    if not request.session.get("operator"):
        return RedirectResponse(url="/?expired=1", status_code=303)
    return None


def render(request: Request, template: str, context: dict[str, Any] | None = None, *, status_code: int = 200):
    payload = dict(context or {})
    payload["operator"] = request.session.get("operator")
    return templates.TemplateResponse(request, template, payload, status_code=status_code)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, expired: int = 0):
    return render(
        request,
        "home.html",
        {
            "error": "*** OPERATOR SESSION EXPIRED - SIGN IN AGAIN ***" if expired else None,
            "operator_hint": "OP100",
            "pin_hint": "2468",
        },
    )


@app.post("/login")
def login(request: Request, op_id: str = Form(""), op_pin: str = Form("")):
    operator = OPERATORS.get(op_id.strip().upper())
    if not operator or operator["pin"] != op_pin.strip():
        return render(
            request,
            "home.html",
            {
                "error": "*** INVALID OPERATOR ID OR PIN ***",
                "operator_hint": "OP100",
                "pin_hint": "2468",
            },
            status_code=401,
        )

    request.session.clear()
    request.session["operator"] = op_id.strip().upper()
    request.session["operator_name"] = operator["display_name"]
    request.session["slow_once_seen"] = {}
    request.session["override_approved"] = {}
    return RedirectResponse(url="/members", status_code=303)


@app.post("/session/start")
def start_session(request: Request):
    """Backwards-compatible synthetic session shortcut used only by tests/dev tooling."""
    request.session.clear()
    request.session["operator"] = "OP100"
    request.session["operator_name"] = "DEMO OPERATOR"
    request.session["slow_once_seen"] = {}
    request.session["override_approved"] = {}
    return RedirectResponse(url="/members", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    if redirect := require_session(request):
        return redirect
    return render(request, "help.html")


@app.get("/members", response_class=HTMLResponse)
def member_search(request: Request):
    if redirect := require_session(request):
        return redirect
    return render(request, "members.html", {"error": None})


@app.post("/members/search", response_class=HTMLResponse)
def search_member(request: Request, f_14: str = Form("")):
    if redirect := require_session(request):
        return redirect

    member_id = f_14.strip()
    if not member_id.isdigit() or len(member_id) != 6:
        return render(
            request,
            "members.html",
            {"error": "*** INVALID MEMBER NUMBER ***", "entered": member_id},
            status_code=422,
        )

    member = db.get_member(member_id)
    if not member:
        return render(
            request,
            "members.html",
            {"error": "*** NO MEMBER FOUND ***", "entered": member_id},
            status_code=200,
        )
    return RedirectResponse(url=f"/members/{member_id}", status_code=303)


@app.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return render(request, "member_detail.html", {"member": member})


@app.get("/members/{member_id}/profile", response_class=HTMLResponse)
def member_profile(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    profile = db.get_profile(member_id)
    if not member or not profile:
        raise HTTPException(status_code=404, detail="Member profile not found")
    return render(request, "profile.html", {"member": member, "profile": profile})


@app.get("/members/{member_id}/accounts", response_class=HTMLResponse)
def accounts(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if member["scenario"] == "permission_denied":
        return render(request, "access_denied.html", {"member": member}, status_code=403)

    approved = request.session.get(
        "override_approved",
        {},
    )

    show_override_dialog = (
        member["scenario"] == "unexpected_dialog"
        and not approved.get(member_id)
    )

    defer_accounts_frame = (
        member["scenario"] == "slow_once"
        and consume_slow_once(
            request,
            member_id,
        )
    )

    return render(
        request,
        "accounts.html",
        {
            "member": member,
            "show_override_dialog": (
                show_override_dialog
            ),
            "defer_accounts_frame": (
                defer_accounts_frame
            ),
        },
    )

@app.post("/members/{member_id}/override")
def resolve_override(request: Request, member_id: str, decision: str = Form(...)):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if decision == "continue":
        approved = dict(request.session.get("override_approved", {}))
        approved[member_id] = True
        request.session["override_approved"] = approved
        return RedirectResponse(url=f"/members/{member_id}/accounts", status_code=303)

    if decision == "cancel":
        return RedirectResponse(url=f"/members/{member_id}", status_code=303)

    raise HTTPException(status_code=400, detail="Unknown override decision")


@app.get(
    "/members/{member_id}/accounts/frame",
    response_class=HTMLResponse,
)
def accounts_frame(
    request: Request,
    member_id: str,
    recovered: int = 0,
):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # delayed = maybe_apply_slow_once(request, member_id)
    accounts_data = db.get_accounts(
        member_id
    )

    return render(
        request,
        "account_frame.html",
        {
            "member": member,
            "accounts": accounts_data,
            "delayed": bool(recovered),
        },
    )


@app.get("/members/{member_id}/accounts/new", response_class=HTMLResponse)
def new_account(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return render(request, "new_account.html", {"member": member, "error": None})


@app.post("/members/{member_id}/accounts/new/review", response_class=HTMLResponse)
def review_account(
    request: Request,
    member_id: str,
    acct_type: str = Form(...),
    nick_27: str = Form(""),
    stmt_mode: str = Form(...),
    dep_amt: str = Form("0"),
):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    try:
        amount = float(dep_amt)
    except ValueError:
        return render(
            request,
            "new_account.html",
            {"member": member, "error": "*** INITIAL DEPOSIT MUST BE NUMERIC ***"},
            status_code=422,
        )

    if amount < 0:
        return render(
            request,
            "new_account.html",
            {"member": member, "error": "*** INITIAL DEPOSIT CANNOT BE NEGATIVE ***"},
            status_code=422,
        )

    pending = {
        "member_id": member_id,
        "account_type": acct_type,
        "nickname": nick_27.strip() or "UNNAMED",
        "statement_delivery": stmt_mode,
        "initial_deposit": amount,
    }
    request.session["pending_subaccount"] = pending
    return render(request, "review_account.html", {"member": member, "pending": pending})


@app.post("/members/{member_id}/accounts/new/confirm", response_class=HTMLResponse)
def confirm_account(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    pending = request.session.get("pending_subaccount")
    if not member or not pending or pending.get("member_id") != member_id:
        raise HTTPException(status_code=409, detail="No pending sub-account review exists")

    confirmation = db.create_subaccount(
        member_id=member_id,
        account_type=str(pending["account_type"]),
        nickname=str(pending["nickname"]),
        statement_delivery=str(pending["statement_delivery"]),
        initial_deposit=float(pending["initial_deposit"]),
    )
    request.session.pop("pending_subaccount", None)
    return render(
        request,
        "account_created.html",
        {"member": member, "confirmation": confirmation},
    )


@app.get("/members/{member_id}/transfer", response_class=HTMLResponse)
def transfer_form(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return render(
        request,
        "transfer.html",
        {"member": member, "accounts": db.get_accounts(member_id), "error": None},
    )


@app.post("/members/{member_id}/transfer/review", response_class=HTMLResponse)
def transfer_review(
    request: Request,
    member_id: str,
    from_acct: int = Form(...),
    to_acct: int = Form(...),
    amount: str = Form(...),
):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    accounts_data = db.get_accounts(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    try:
        parsed_amount = round(float(amount), 2)
    except ValueError:
        return render(
            request,
            "transfer.html",
            {"member": member, "accounts": accounts_data, "error": "*** TRANSFER AMOUNT MUST BE NUMERIC ***"},
            status_code=422,
        )

    source = db.get_account(member_id, from_acct)
    destination = db.get_account(member_id, to_acct)
    if not source or not destination:
        error = "*** ACCOUNT NOT FOUND ***"
    elif from_acct == to_acct:
        error = "*** SOURCE AND DESTINATION ACCOUNTS MUST DIFFER ***"
    elif parsed_amount <= 0:
        error = "*** TRANSFER AMOUNT MUST BE GREATER THAN ZERO ***"
    elif float(source["balance"]) < parsed_amount:
        error = "*** INSUFFICIENT FUNDS ***"
    else:
        error = None

    if error:
        return render(
            request,
            "transfer.html",
            {"member": member, "accounts": accounts_data, "error": error},
            status_code=422,
        )

    pending = {
        "member_id": member_id,
        "from_account_id": from_acct,
        "to_account_id": to_acct,
        "amount": parsed_amount,
    }
    request.session["pending_transfer"] = pending
    return render(
        request,
        "transfer_review.html",
        {"member": member, "pending": pending, "source": source, "destination": destination},
    )


@app.post("/members/{member_id}/transfer/confirm", response_class=HTMLResponse)
def transfer_confirm(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    pending = request.session.get("pending_transfer")
    member = db.get_member(member_id)
    if not member or not pending or pending.get("member_id") != member_id:
        raise HTTPException(status_code=409, detail="No pending transfer review exists")

    try:
        confirmation = db.transfer_funds(
            member_id=member_id,
            from_account_id=int(pending["from_account_id"]),
            to_account_id=int(pending["to_account_id"]),
            amount=float(pending["amount"]),
        )
    except ValueError as exc:
        return render(
            request,
            "transaction_error.html",
            {"member": member, "message": str(exc), "return_url": f"/members/{member_id}/transfer"},
            status_code=409,
        )

    request.session.pop("pending_transfer", None)
    return render(
        request,
        "transaction_complete.html",
        {
            "member": member,
            "transaction_type": "FUNDS TRANSFER",
            "confirmation": confirmation,
            "amount": float(pending["amount"]),
        },
    )


@app.get("/members/{member_id}/withdraw", response_class=HTMLResponse)
def withdrawal_form(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return render(
        request,
        "withdrawal.html",
        {"member": member, "accounts": db.get_accounts(member_id), "error": None},
    )


@app.post("/members/{member_id}/withdraw/review", response_class=HTMLResponse)
def withdrawal_review(
    request: Request,
    member_id: str,
    from_acct: int = Form(...),
    amount: str = Form(...),
):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    accounts_data = db.get_accounts(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    try:
        parsed_amount = round(float(amount), 2)
    except ValueError:
        return render(
            request,
            "withdrawal.html",
            {"member": member, "accounts": accounts_data, "error": "*** WITHDRAWAL AMOUNT MUST BE NUMERIC ***"},
            status_code=422,
        )

    source = db.get_account(member_id, from_acct)
    if not source:
        error = "*** ACCOUNT NOT FOUND ***"
    elif parsed_amount <= 0:
        error = "*** WITHDRAWAL AMOUNT MUST BE GREATER THAN ZERO ***"
    elif float(source["balance"]) < parsed_amount:
        error = "*** INSUFFICIENT FUNDS ***"
    else:
        error = None

    if error:
        return render(
            request,
            "withdrawal.html",
            {"member": member, "accounts": accounts_data, "error": error},
            status_code=422,
        )

    pending = {"member_id": member_id, "account_id": from_acct, "amount": parsed_amount}
    request.session["pending_withdrawal"] = pending
    return render(
        request,
        "withdrawal_review.html",
        {"member": member, "pending": pending, "source": source},
    )


@app.post("/members/{member_id}/withdraw/confirm", response_class=HTMLResponse)
def withdrawal_confirm(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    pending = request.session.get("pending_withdrawal")
    member = db.get_member(member_id)
    if not member or not pending or pending.get("member_id") != member_id:
        raise HTTPException(status_code=409, detail="No pending withdrawal review exists")

    try:
        confirmation = db.withdraw_funds(
            member_id=member_id,
            account_id=int(pending["account_id"]),
            amount=float(pending["amount"]),
        )
    except ValueError as exc:
        return render(
            request,
            "transaction_error.html",
            {"member": member, "message": str(exc), "return_url": f"/members/{member_id}/withdraw"},
            status_code=409,
        )

    request.session.pop("pending_withdrawal", None)
    return render(
        request,
        "transaction_complete.html",
        {
            "member": member,
            "transaction_type": "CASH WITHDRAWAL",
            "confirmation": confirmation,
            "amount": float(pending["amount"]),
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "demo_app.app:app",
        host=os.getenv("LEGACYBANK_HOST", "127.0.0.1"),
        port=int(os.getenv("LEGACYBANK_PORT", "8000")),
        reload=True,
    )
