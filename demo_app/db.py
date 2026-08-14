from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from .fixtures import ACCOUNTS, MEMBERS


def db_path() -> Path:
    configured = os.getenv("LEGACYBANK_DB_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "legacybank.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS members (
                member_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                branch TEXT NOT NULL,
                scenario TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                account_type TEXT NOT NULL,
                masked_number TEXT NOT NULL,
                balance REAL NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(member_id)
            );

            CREATE TABLE IF NOT EXISTS created_subaccounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                account_type TEXT NOT NULL,
                nickname TEXT NOT NULL,
                statement_delivery TEXT NOT NULL,
                initial_deposit REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        member_count = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        if member_count == 0:
            conn.executemany(
                """
                INSERT INTO members(member_id, name, status, branch, scenario)
                VALUES(:member_id, :name, :status, :branch, :scenario)
                """,
                MEMBERS,
            )
            conn.executemany(
                """
                INSERT INTO accounts(member_id, account_type, masked_number, balance)
                VALUES(:member_id, :account_type, :masked_number, :balance)
                """,
                ACCOUNTS,
            )


def get_member(member_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
    return dict(row) if row else None


def get_accounts(member_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT account_type, masked_number, balance FROM accounts WHERE member_id = ? ORDER BY id",
            (member_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_subaccount(
    *,
    member_id: str,
    account_type: str,
    nickname: str,
    statement_delivery: str,
    initial_deposit: float,
) -> str:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO created_subaccounts(
                member_id, account_type, nickname, statement_delivery, initial_deposit
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (member_id, account_type, nickname, statement_delivery, initial_deposit),
        )
        row_id = int(cursor.lastrowid)
    return f"C-{row_id:07d}"
