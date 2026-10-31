# Contributing to BloodLink

Thanks for helping. BloodLink handles sensitive health-adjacent data, so a few rules are firm.

## Set up
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
python seed.py          # fake data, empty database only
python app.py           # http://127.0.0.1:5000
python -m pytest        # must pass before you open a pull request
```
To run the tests against PostgreSQL: `TEST_DATABASE_URL=postgresql://user:pass@host/db python -m pytest`.

## Ground rules
1. **Only a hospital can confirm a donation.** Nothing else (chat, forms, donors, patients) may change unit counts.
2. **No real personal data** in code, tests, screenshots or issues. Use fictional people and `example.com`.
3. **Never commit secrets** (`.env`, keys, database files).
4. Every new feature needs tests, and every new personal-data field needs an export, an erasure rule and a
   retention rule (see `utils/privacy.py` and `utils/maintenance.py`).
5. Keep it accessible: labels on inputs, keyboard support, visible focus, no information by colour alone.

## Pull requests
Small, focused branches with a clear description. Explain *why*, not only *what*. Be kind in reviews.

## Reporting a security problem
Please do not open a public issue. See [SECURITY.md](SECURITY.md).
