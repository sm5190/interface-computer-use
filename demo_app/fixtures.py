"""Synthetic, deterministic LegacyBank fixtures. No real PII is used."""

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
