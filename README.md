# Interface Computer Use

Interface.ai SWE take-home reference implementation.

## Current milestone: LegacyBank proxy target

LegacyBank is a local, synthetic, intentionally legacy-style banking operations console used as the live UI target for the computer-use system.

### Run

```powershell
uv sync
uv run python -m demo_app.app
```

Open `http://127.0.0.1:8000`.

Synthetic training login:

- Operator ID: `OP100`
- PIN: `2468`

All member/account/profile data is synthetic.

### Useful fixtures

- `100001`: normal member
- `100002`: normal member with different balances
- `100003`: no savings account
- `100004`: first account-frame load is delayed once
- `100005`: permission denied
- `100006`: supervisor-override dialog for human-handoff testing
- `999999`: member not found

### Target workflows

- Lookup member savings balance
- Open a new sub-account and reach high-risk confirmation
- Transfer funds between a member's accounts and reach high-risk confirmation
- Withdraw funds and reach high-risk confirmation
- Open member profile
- Resolve a synthetic supervisor-override dialog

The final computer-use automation will enforce policy before high-risk confirmation actions. The target application itself intentionally permits those actions so policy behavior can be demonstrated externally.
