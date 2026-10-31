
<p align="center">
  <img src="docs/images/banner.png" alt="BloodLink: Blood Donor and Emergency Request Network" width="100%">
</p>

<p align="center">
  <a href="../../actions"><img alt="tests" src="../../actions/workflows/ci.yml/badge.svg"></a>
  <img alt="license" src="https://img.shields.io/badge/license-MIT-c8102e">
  <img alt="python" src="https://img.shields.io/badge/python-3.12%2B-3a0815?logo=python&logoColor=white">
  <img alt="flask" src="https://img.shields.io/badge/Flask-3.0-3a0815?logo=flask&logoColor=white">
  <img alt="database" src="https://img.shields.io/badge/SQLite%20%7C%20PostgreSQL-supported-6e0f26">
  <img alt="languages" src="https://img.shields.io/badge/UI-English%20%7C%20%D8%A7%D8%B1%D8%AF%D9%88%20%7C%20%D8%B3%D9%86%DA%8C%D9%8A-c8102e">
  <img alt="status" src="https://img.shields.io/badge/status-university%20project-6f6673">
</p>

<h3 align="center">Connecting donors, patients and hospitals, with the hospital in charge of every decision that matters.</h3>

<p align="center">
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-screenshots">Screenshots</a> ·
  <a href="#-how-it-works">How it works</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-documentation">Docs</a> ·
  <a href="#-licence">Licence</a>
</p>

> **University project.** BloodLink is built and operated by **Muhammad Ali** for the Software Engineering course
> (*CSC-206, Blood Donor & Emergency Request Network*). It is **not** a medical service. It never decides who may donate
> or receive blood: hospitals decide eligibility, testing and crossmatching.

---

## 🩸 The problem and the idea

In an emergency, families message dozens of people. Requests are unverified, donors get too many or too few calls, and nobody
knows how many units have really arrived.

**BloodLink puts one controlled flow in place of that chaos:**

* A **patient** posts a request for the hospital where they are treated.
* The **hospital** checks it and approves or rejects it, so donors only see real, verified needs.
* **Compatible, available donors** are notified, nearest first, and can offer to help.
* The **hospital** screens each donor and **confirms every donation**. A request for several units stays open until all units are confirmed.

## 🔄 How it works

<p align="center"><img src="docs/images/flow.png" alt="A request moves from the patient to the hospital, to donors, back to the hospital for confirmation, then to fulfilled" width="100%"></p>

1. **Patient** posts a request: blood group, number of units, hospital and how urgent it is.
2. **Hospital** reviews it. After approving, it sees **donors near the hospital** on a map (GPS or the saved hospital location).
3. **Donors** with a compatible blood group are notified and can offer to help. An offer only means "I am willing". It is never counted as blood.
4. **Hospital** contacts and screens donors. Donors show a **QR code** when they arrive. The hospital then **confirms each donation**.
5. The request becomes **Fulfilled** when the confirmed units reach the units required. Urgent requests nobody answers are escalated, and old requests expire.

> **The key rule:** totals come only from donations the hospital has confirmed, never from what donors claim.
> Example: 3 units needed. The hospital confirms donor A (1 of 3, *Partially Fulfilled*), then B (2 of 3), then C (3 of 3, *Fulfilled*).
> Confirmations are locked, so two staff members can never claim the same last unit, and a request can never go over its limit.

## ✨ Features

<p align="center"><img src="docs/images/features.png" alt="BloodLink features: hospital verification, matching, nearby donors, verified donor badge, QR check-in, camps and stock, chat, languages, security" width="100%"></p>

### Four roles

<p align="center"><img src="docs/images/roles.png" alt="Patient, donor, hospital and admin roles" width="100%"></p>

| Role | What they can do |
|---|---|
| **Patient or family** | Post, track and cancel requests. See progress unit by unit. Chat with donors who offered. Export or delete their own data. |
| **Donor** | Register with a CNIC number. Set availability (with the 3-month rest period). See compatible requests, offer or withdraw, and say "I donated" (the hospital then checks it). Read health reports as PDF. Use **QR check-in**, get certificates and badges, join **donation camps**. Upload a CNIC image to earn the **Verified donor** badge. |
| **Hospital** | Approve requests. Post **emergency requests**. See **nearby donors on a map**. Contact, schedule and screen donors. Write health reports. Confirm donations. Scan donor and camp **QR codes**. Run **camps** with a waiting list. Manage **blood stock**: camp donations are added to it automatically. View analytics. |
| **Admin** | Verify hospitals. Manage accounts. **Review CNIC uploads** and approve or reject them. See every donor's details. Read analytics, the activity log, the privacy inbox and reported chats. |

**Good to know**

* **Verified donor badge:** the CNIC image is stored encrypted and only an administrator can open it. A donor without a verified CNIC can still donate, but does not show the badge.
* **Languages and themes:** English, Urdu and Sindhi (full right-to-left layout), and three themes: Light, Dark and Classic.
* **Matching:** rule-based and explainable, with correct blood-group compatibility. No machine learning.
* **Alerts:** SMS, WhatsApp, push and email are all opt-in and stay off until you configure them.
* **Public API:** read-only, with docs at `/api/v1/docs`.

## 📸 Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/home.png" alt="Home page"><br><sub><b>Home:</b> pick a blood group and see live requests</sub></td>
    <td width="50%"><img src="docs/screenshots/donor-dashboard.png" alt="Donor dashboard"><br><sub><b>Donor dashboard:</b> availability, eligibility and badges</sub></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/hospital-donor-coordination.png" alt="Hospital donor coordination"><br><sub><b>Hospital:</b> contact, screen and confirm donors</sub></td>
    <td><img src="docs/screenshots/patient-request-progress.png" alt="Patient request progress"><br><sub><b>Patient:</b> see confirmed units for a request</sub></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/chat-thread-patient.png" alt="Chat"><br><sub><b>Chat:</b> donor, family and hospital in one thread</sub></td>
    <td><img src="docs/screenshots/camps.png" alt="Donation camps"><br><sub><b>Donation camps:</b> sign up or join the waiting list</sub></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/qr-checkin-donor.png" alt="QR check-in"><br><sub><b>QR check-in:</b> show the code on arrival</sub></td>
    <td><img src="docs/screenshots/hospital-stock.png" alt="Blood stock"><br><sub><b>Blood stock:</b> public, hospital-reported units</sub></td>
  </tr>
</table>

<sub>All screenshots use fake demo data. More are in <a href="docs/screenshots">docs/screenshots</a>.</sub>

## 🚀 Quick start

You need **Python 3.12 or newer**.

```bash
git clone <your-repository-url>
cd BloodLink

python -m venv venv
venv\Scripts\activate              # macOS / Linux: source venv/bin/activate
pip install -r requirements.txt

python app.py                      # then open http://127.0.0.1:5000
```

On the first run, BloodLink fills an **empty** database with fake demo data, so you can log in straight away.
You can also run `python seed.py` yourself. It only ever seeds an empty database. Set `BLOODLINK_NO_AUTOSEED=1` to turn the automatic step off.

Using VS Code? Open the folder, pick the `venv` interpreter and press **F5**. See [docs/VSCODE.md](docs/VSCODE.md).

### Demo logins

These accounts are fake. Choose the role on the login page first.

| Role | Email | Password |
|---|---|---|
| Admin | `admin@bloodlink.com` | `Admin123` |
| Hospital | `civil@sukkurhospital.com` | `Hospital123` |
| Donor | `ahmed.ali@example.com` | `Donor123` |
| Patient | `rizwan@example.com` | `Patient123` |

For the chat demo, open two windows: donor `bilal@example.com` / `Donor123` and patient `ayesha@example.com` / `Patient123`.

### Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

To run the same tests on PostgreSQL: `TEST_DATABASE_URL=postgresql://user:pass@host/db python -m pytest`.
Background jobs (reminders, escalation, queued messages): `flask --app app jobs`, every 5 minutes.

## 🧱 Tech stack

<p align="center"><img src="docs/images/arch.png" alt="Layers: browser, routes, services, models, database" width="100%"></p>

| Layer | Used |
|---|---|
| Backend | Python 3.12, Flask 3, Flask-SQLAlchemy, Flask-Migrate (Alembic) |
| Database | SQLite for local use, PostgreSQL for production |
| Frontend | Jinja templates, Bootstrap 5, Font Awesome, vanilla JavaScript. No CDN: everything is served by the app |
| Extras | `segno` (QR codes), `reportlab` (PDF reports and certificates), `cryptography` (encrypted CNIC files) |
| Quality | pytest suite, GitHub Actions CI, Docker image, `render.yaml` for hosting |

<details>
<summary><b>Project folder map</b></summary>

```
BloodLink/
├── app.py            application factory, security headers, language and error handling
├── config.py         settings from environment variables
├── models/           database models (users, requests, donations, camps, CNIC ...)
├── routes/           one blueprint per area (auth, donor, patient, hospital, admin, chat ...)
├── utils/            matching, geo, QR, notifications, i18n and other services
├── templates/        Jinja pages
├── static/           CSS, JavaScript and bundled fonts
├── migrations/       Alembic database migrations
├── seed.py           fake demo data
├── tests/            automated tests
└── docs/             guides, diagrams, images and screenshots
```
</details>

## 🔒 Security and privacy

* Passwords are hashed. Sessions are protected and every form carries a CSRF token.
* A strict Content-Security-Policy, with no third-party scripts, fonts or analytics.
* Every page checks the user's role. Hospital and admin areas are separate.
* Rate limiting on login and uploads, an audit log for sensitive actions, and optional two-factor login.
* A donor's phone and email are shown only to signed-in patients and hospitals, and only if the donor agreed.
* CNIC images are checked by file signature, limited in size, encrypted at rest, and viewable only by administrators. Every view is logged.
* Users can export or delete their data. To report a security problem, see [SECURITY.md](SECURITY.md).

## ⚙️ Configuration

Settings come from environment variables or a `.env` file (copy `.env.example`). **Nothing is needed to run locally.**

| Variable | Purpose |
|---|---|
| `SECRET_KEY`, `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Required in production |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `PUBLIC_BASE_URL` | Real email ([docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md)). Without it, links print in the terminal |
| `LOCAL_UTC_OFFSET_MINUTES` | Clock used for camp times (default `300`, Pakistan) |
| `TWILIO_*` and `NOTIFY_PROVIDER=twilio` | SMS and WhatsApp |
| `VAPID_*` | Browser push (`python scripts/gen_vapid_keys.py`) |
| `ANTHROPIC_API_KEY` | Chat "Translate" button |
| `REQUIRE_2FA_ROLES=admin,hospital` | Force two-factor login for those roles |

Other options (Redis, Sentry, JSON logs, Alembic) are in [docs/DETAILS.md](docs/DETAILS.md).

## ☁️ Deploy for free

Use GitHub, **Neon** (free PostgreSQL) and **Render** (free hosting) with the included `render.yaml`.
The free plan puts the site to sleep after 15 minutes idle and has no cron, so background jobs run inside the web process.
Step by step: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

## ⚠️ Known limitations

* Not a medical device. Eligibility rules (such as the 90-day interval) are configurable placeholders that a blood bank must confirm.
* SMS/WhatsApp, push, translation, Redis and Sentry were tested with fakes only. Try each once with your own keys.
* The Urdu and Sindhi wording is a first draft and needs a native speaker's review. Legal, admin and About pages stay in English.
* Chat uses polling, so messages can take about 4 seconds to appear. Location sharing and push need https (or localhost).
* The policies were written for this project and are **not legal advice**. Have them reviewed before any real use.

## 📚 Documentation

| | |
|---|---|
| [Deployment guide](docs/DEPLOY.md) | [Technical details](docs/DETAILS.md) |
| [Architecture and diagrams](docs/ARCHITECTURE.md) | [VS Code setup](docs/VSCODE.md) |
| [Email setup](docs/EMAIL_SETUP.md) | [Compliance checklist](docs/COMPLIANCE_CHECKLIST.md) |
| [Demo guide](docs/PRESENTATION_GUIDE.md) | [Changelog](CHANGELOG.md) |
| [Contributing](CONTRIBUTING.md) | [Security policy](SECURITY.md) |

## 👤 Author

**Muhammad Ali**: developer and operator of BloodLink, built as a university Software Engineering project.

## 📄 Licence

Released under the **MIT Licence**. See [LICENSE](LICENSE).
You may use, copy, modify and share this software as long as the copyright notice stays with it.
It is provided "as is", without warranty of any kind, and is not intended for real medical use.

<p align="center"><sub>Made with care for people who need blood and the people who give it.</sub></p>
