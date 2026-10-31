# BloodLink — Blood Donor & Emergency Request Network

[![tests](../../actions/workflows/ci.yml/badge.svg)](../../actions) ![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.12%2B-blue)

**Connecting donors, patients and hospitals, with the hospital in charge of every decision that matters.**

A patient posts a blood request, the named hospital reviews it, compatible volunteer donors can offer to help, and the
hospital coordinates them and **confirms each donation**. A request for several units is tracked until every unit is confirmed.

<p>
<img src="docs/screenshots/chat-thread-patient.png" width="49%" alt="Chat between a donor, the patient's family and the hospital">
<img src="docs/screenshots/hospital-donor-coordination.png" width="49%" alt="Hospital coordinates donors and confirms units">
<img src="docs/screenshots/donor-dashboard.png" width="49%" alt="Donor dashboard with badges and availability">
<img src="docs/screenshots/admin-analytics.png" width="49%" alt="Admin analytics">
</p>

> University project. BloodLink is **not** a medical service. It never decides who may donate or receive blood.
> Hospitals decide eligibility, testing and crossmatching.

## How it works

1. **Patient** posts a request (blood group, units, hospital, urgency).
2. **Hospital** reviews it, then approves or rejects.
3. **Compatible donors** are notified and can offer to help. An offer is willingness only, never counted as blood.
4. **Hospital** contacts, schedules and screens donors, then **confirms each donation**.
5. The request becomes *Fulfilled* when confirmed units reach the units required.

> **The key rule:** totals come from hospital-confirmed donation records, never from donor claims. Example: required 3 →
> hospital confirms A (1/3, *Partially Fulfilled*) → B (2/3) → C (3/3, *Fulfilled*). Confirmations are locked so two hospital
> users cannot claim the same last unit, and a confirmation can never exceed the units required.

## Features

| Role | Can do |
|---|---|
| **Patient / family** | Post, track and **cancel** requests, see progress, chat with offering donors, export or delete their data |
| **Donor** | Set availability ("available now"), see compatible requests, offer and **withdraw**, say **"I donated"** (the hospital checks), read **why they are deferred and their health check reports** (PDF), chat, QR check-in, certificates, badges, donation camps |
| **Hospital** | Approve requests, post **emergency requests** that go live at once, contact / schedule / screen donors and **write health check reports**, **confirm donations**, check donors in by QR, run **camps** (waiting list, roster, record donations), manage blood stock, analytics |
| **Admin** | Verify hospitals, manage accounts, analytics, activity log, privacy inbox, review reported chats |

Also included: three **themes** (Light, Dark, Classic; saved in your browser), private **chat** per offer (live timeline, quick replies, one-time location sharing, money/scam flagging, optional
Translate), automatic **escalation** of unanswered urgent requests, **distance-aware** matching (rule-based, explainable, no machine
learning), SMS/WhatsApp/push/email alerts and reminders (opt-in, off until configured), **two-factor login**, password reset, a public
read-only **API** (`/api/v1/docs`), and an **Urdu / Sindhi** interface.

## Quick start

```bash
python -m venv venv
venv\Scripts\activate              # macOS / Linux: source venv/bin/activate
pip install -r requirements.txt
python seed.py                      # fake demo data, into an EMPTY database only
python app.py                       # open http://127.0.0.1:5000
```

Using VS Code? See [docs/VSCODE.md](docs/VSCODE.md) (open the folder, pick the `venv` interpreter, press **F5**).

**Demo logins** (fake data; pick the role on the login page first):

| Role | Email | Password |
|---|---|---|
| Admin | admin@bloodlink.com | Admin123 |
| Hospital | civil@sukkurhospital.com | Hospital123 |
| Donor | ahmed.ali@example.com | Donor123 |
| Patient | rizwan@example.com | Patient123 |

For the chat demo log in as donor `bilal@example.com` / `Donor123` and patient `ayesha@example.com` / `Patient123` in two windows.

**Tests:** `pip install -r requirements-dev.txt`, then `python -m pytest`. To run the same suite on PostgreSQL:
`TEST_DATABASE_URL=postgresql://user:pass@host/db python -m pytest`.

**Background jobs** (reminders, escalation, queued messages): `flask --app app jobs` (schedule every 5 minutes).

## Configuration

Settings come from environment variables or a `.env` file (copy `.env.example`). Nothing is needed to run locally.

| Variable | Purpose |
|---|---|
| `SECRET_KEY`, `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Required in production |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `PUBLIC_BASE_URL` | Real email (see [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md)); without it, links print in the terminal |
| `TWILIO_*` + `NOTIFY_PROVIDER=twilio` | SMS and WhatsApp |
| `VAPID_*` | Browser push (`python scripts/gen_vapid_keys.py`) |
| `ANTHROPIC_API_KEY` | Chat Translate button |
| `REQUIRE_2FA_ROLES=admin,hospital` | Force two-factor login for those roles |

All other options (Redis, Sentry, JSON logs, Alembic) are listed in [docs/DETAILS.md](docs/DETAILS.md).

## Put it online (free)

GitHub + **Neon** (free PostgreSQL) + **Render** (free hosting) using the included `render.yaml`. Step by step, with the free-plan
catches (the site sleeps after 15 minutes idle; no free cron, so the jobs run inside the web process): **[docs/DEPLOY.md](docs/DEPLOY.md)**.

## Known limitations

* Not a medical device; eligibility rules (e.g. the 90-day interval) are configurable placeholders to be confirmed by a blood bank.
* SMS/WhatsApp, push, translation, Redis and Sentry are tested with fakes only, not against live accounts. Try each once with your own keys.
* Urdu and Sindhi text is a first draft and needs review by a native speaker. Only navigation, sign-in and chat are translated.
* Chat uses polling, so messages can take about 4 seconds to appear. Location sharing and push need https (or localhost).
* Policies are drafted for this project and are **not legal advice**; have them reviewed before real use.

## More documentation

[Deployment guide](docs/DEPLOY.md) · [Full technical details](docs/DETAILS.md) · [Architecture and diagrams](docs/ARCHITECTURE.md) · [VS Code setup](docs/VSCODE.md) ·
[Email setup](docs/EMAIL_SETUP.md) · [Compliance checklist](docs/COMPLIANCE_CHECKLIST.md) · [Demo guide](docs/PRESENTATION_GUIDE.md) ·
[Changelog](CHANGELOG.md)

## Contributing and licence

MIT licensed ([LICENSE](LICENSE)). Contributions welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
