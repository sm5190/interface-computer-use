from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from .fixtures import ACCOUNTS, MEMBERS, PROFILES


def db_path() -> Path:
    configured = os.getenv("LEGACYBANK_DB_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "legacybank.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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

            CREATE TABLE IF NOT EXISTS profiles (
                member_id TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                address TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(member_id)
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

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                from_account_id INTEGER,
                to_account_id INTEGER,
                amount REAL NOT NULL,
                confirmation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Members and profiles have member_id primary keys, so they can be
        # safely backfilled without duplicating existing fixture records.
        conn.executemany(
            """
            INSERT OR IGNORE INTO members(
                member_id,
                name,
                status,
                branch,
                scenario
            )
            VALUES(
                :member_id,
                :name,
                :status,
                :branch,
                :scenario
            )
            """,
            MEMBERS,
        )

        conn.executemany(
            """
            INSERT OR IGNORE INTO profiles(
                member_id,
                phone,
                email,
                address
            )
            VALUES(
                :member_id,
                :phone,
                :email,
                :address
            )
            """,
            PROFILES,
        )

        # Accounts use an auto-increment ID, so INSERT OR IGNORE alone would
        # not prevent duplicate seeded accounts. Check the stable synthetic
        # account identity explicitly.
        for account in ACCOUNTS:
            existing = conn.execute(
                """
                SELECT 1
                FROM accounts
                WHERE member_id = ?
                  AND account_type = ?
                  AND masked_number = ?
                """,
                (
                    account["member_id"],
                    account["account_type"],
                    account["masked_number"],
                ),
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO accounts(
                        member_id,
                        account_type,
                        masked_number,
                        balance
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        account["member_id"],
                        account["account_type"],
                        account["masked_number"],
                        account["balance"],
                    ),
                )

        conn.commit()

def get_member(member_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
    return dict(row) if row else None


def get_profile(member_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE member_id = ?", (member_id,)).fetchone()
    return dict(row) if row else None


def get_accounts(member_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, account_type, masked_number, balance
            FROM accounts
            WHERE member_id = ?
            ORDER BY id
            """,
            (member_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_account(member_id: str, account_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, member_id, account_type, masked_number, balance
            FROM accounts
            WHERE member_id = ? AND id = ?
            """,
            (member_id, account_id),
        ).fetchone()
    return dict(row) if row else None


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


def transfer_funds(*, member_id: str, from_account_id: int, to_account_id: int, amount: float) -> str:
    if from_account_id == to_account_id:
        raise ValueError("SOURCE AND DESTINATION ACCOUNTS MUST DIFFER")
    if amount <= 0:
        raise ValueError("TRANSFER AMOUNT MUST BE GREATER THAN ZERO")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ? AND member_id = ?",
            (from_account_id, member_id),
        ).fetchone()
        destination = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ? AND member_id = ?",
            (to_account_id, member_id),
        ).fetchone()
        if not source or not destination:
            raise ValueError("ACCOUNT NOT FOUND")
        if float(source["balance"]) < amount:
            raise ValueError("INSUFFICIENT FUNDS")

        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_account_id))
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_account_id))

        confirmation = f"T-{int(conn.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM transactions').fetchone()[0]):07d}"
        conn.execute(
            """
            INSERT INTO transactions(
                member_id, transaction_type, from_account_id, to_account_id, amount, confirmation
            ) VALUES (?, 'TRANSFER', ?, ?, ?, ?)
            """,
            (member_id, from_account_id, to_account_id, amount, confirmation),
        )
    return confirmation


def withdraw_funds(*, member_id: str, account_id: int, amount: float) -> str:
    if amount <= 0:
        raise ValueError("WITHDRAWAL AMOUNT MUST BE GREATER THAN ZERO")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ? AND member_id = ?",
            (account_id, member_id),
        ).fetchone()
        if not account:
            raise ValueError("ACCOUNT NOT FOUND")
        if float(account["balance"]) < amount:
            raise ValueError("INSUFFICIENT FUNDS")

        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, account_id))
        confirmation = f"W-{int(conn.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM transactions').fetchone()[0]):07d}"
        conn.execute(
            """
            INSERT INTO transactions(
                member_id, transaction_type, from_account_id, to_account_id, amount, confirmation
            ) VALUES (?, 'WITHDRAWAL', ?, NULL, ?, ?)
            """,
            (member_id, account_id, amount, confirmation),
        )
    return confirmation
