"""Synthetic, deterministic LegacyBank fixtures. No real PII is used."""

OPERATORS = {
    "OP100": {
        "pin": "2468",
        "display_name": "DEMO OPERATOR",
        "role": "MEMBER SERVICES",
    }
}

MEMBERS = [
    {
        "member_id": "100001",
        "name": "SAMPLE MEMBER A",
        "status": "ACTIVE",
        "branch": "021",
        "scenario": "normal",
    },
    {
        "member_id": "100002",
        "name": "SAMPLE MEMBER B",
        "status": "ACTIVE",
        "branch": "014",
        "scenario": "normal",
    },
    {
        "member_id": "100003",
        "name": "SAMPLE MEMBER C",
        "status": "ACTIVE",
        "branch": "021",
        "scenario": "no_savings",
    },
    {
        "member_id": "100004",
        "name": "SAMPLE MEMBER D",
        "status": "ACTIVE",
        "branch": "008",
        "scenario": "slow_once",
    },
    {
        "member_id": "100005",
        "name": "SAMPLE MEMBER E",
        "status": "ACTIVE",
        "branch": "033",
        "scenario": "permission_denied",
    },
    {
        "member_id": "100006",
        "name": "SAMPLE MEMBER F",
        "status": "ACTIVE",
        "branch": "033",
        "scenario": "unexpected_dialog",
    },
]

PROFILES = [
    {
        "member_id": "100001",
        "phone": "(555) 010-1001",
        "email": "sample.a@example.invalid",
        "address": "101 Demo Street, Training City, VA 24000",
    },
    {
        "member_id": "100002",
        "phone": "(555) 010-1002",
        "email": "sample.b@example.invalid",
        "address": "102 Demo Street, Training City, VA 24000",
    },
    {
        "member_id": "100003",
        "phone": "(555) 010-1003",
        "email": "sample.c@example.invalid",
        "address": "103 Demo Street, Training City, VA 24000",
    },
    {
        "member_id": "100004",
        "phone": "(555) 010-1004",
        "email": "sample.d@example.invalid",
        "address": "104 Demo Street, Training City, VA 24000",
    },
    {
        "member_id": "100005",
        "phone": "(555) 010-1005",
        "email": "sample.e@example.invalid",
        "address": "105 Demo Street, Training City, VA 24000",
    },
    {
        "member_id": "100006",
        "phone": "(555) 010-1006",
        "email": "sample.f@example.invalid",
        "address": "106 Demo Street, Training City, VA 24000",
    },
]

ACCOUNTS = [
    {"member_id": "100001", "account_type": "CHECKING", "masked_number": "***4101", "balance": 2143.92},
    {"member_id": "100001", "account_type": "SAVINGS", "masked_number": "***9821", "balance": 8431.20},
    {"member_id": "100002", "account_type": "CHECKING", "masked_number": "***1129", "balance": 901.10},
    {"member_id": "100002", "account_type": "SAVINGS", "masked_number": "***5520", "balance": 4201.19},
    {"member_id": "100003", "account_type": "CHECKING", "masked_number": "***7110", "balance": 527.66},
    {"member_id": "100004", "account_type": "CHECKING", "masked_number": "***8101", "balance": 1320.44},
    {"member_id": "100004", "account_type": "SAVINGS", "masked_number": "***8191", "balance": 5200.05},
    {"member_id": "100005", "account_type": "SAVINGS", "masked_number": "***1005", "balance": 7750.00},
    {"member_id": "100006", "account_type": "CHECKING", "masked_number": "***1006", "balance": 88.12},
    {"member_id": "100006", "account_type": "SAVINGS", "masked_number": "***6001", "balance": 615.84},
]
