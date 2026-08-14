from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .scenarios import maybe_apply_slow_once

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
        return RedirectResponse(url="/", status_code=303)
    return None


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {})


@app.post("/session/start")
def start_session(request: Request):
    request.session.clear()
    request.session["operator"] = "DEMO-OPERATOR"
    request.session["slow_once_seen"] = {}
    return RedirectResponse(url="/members", status_code=303)


@app.get("/members", response_class=HTMLResponse)
def member_search(request: Request):
    if redirect := require_session(request):
        return redirect
    return templates.TemplateResponse(request, "members.html", {"error": None})


@app.post("/members/search", response_class=HTMLResponse)
def search_member(request: Request, f_14: str = Form("")):
    if redirect := require_session(request):
        return redirect

    member_id = f_14.strip()
    if not member_id.isdigit() or len(member_id) != 6:
        return templates.TemplateResponse(
            request,
            "members.html",
            {"error": "*** INVALID MEMBER NUMBER ***", "entered": member_id},
            status_code=422,
        )

    member = db.get_member(member_id)
    if not member:
        return templates.TemplateResponse(
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
    return templates.TemplateResponse(request, "member_detail.html", {"member": member})


@app.get("/members/{member_id}/accounts", response_class=HTMLResponse)
def accounts(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if member["scenario"] == "permission_denied":
        return templates.TemplateResponse(
            request,
            "access_denied.html",
            {"member": member},
            status_code=403,
        )

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "member": member,
            "show_override_dialog": member["scenario"] == "unexpected_dialog",
        },
    )


@app.get("/members/{member_id}/accounts/frame", response_class=HTMLResponse)
def accounts_frame(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    delayed = maybe_apply_slow_once(request, member_id)
    accounts_data = db.get_accounts(member_id)
    return templates.TemplateResponse(
        request,
        "account_frame.html",
        {"member": member, "accounts": accounts_data, "delayed": delayed},
    )


@app.get("/members/{member_id}/accounts/new", response_class=HTMLResponse)
def new_account(request: Request, member_id: str):
    if redirect := require_session(request):
        return redirect
    member = db.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return templates.TemplateResponse(request, "new_account.html", {"member": member, "error": None})


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
        return templates.TemplateResponse(
            request,
            "new_account.html",
            {"member": member, "error": "*** INITIAL DEPOSIT MUST BE NUMERIC ***"},
            status_code=422,
        )

    if amount < 0:
        return templates.TemplateResponse(
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
    return templates.TemplateResponse(request, "review_account.html", {"member": member, "pending": pending})


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
    return templates.TemplateResponse(
        request,
        "account_created.html",
        {"member": member, "confirmation": confirmation},
    )


if __name__ == "__main__":
    uvicorn.run(
        "demo_app.app:app",
        host=os.getenv("LEGACYBANK_HOST", "127.0.0.1"),
        port=int(os.getenv("LEGACYBANK_PORT", "8000")),
        reload=True,
    )
