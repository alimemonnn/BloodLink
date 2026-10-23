# 🩸 BloodLink — Blood Donor & Emergency Request Network

<p align="center">
  <img src="docs/screenshots/hospital-donor-coordination.png" alt="BloodLink hospital donor coordination dashboard" width="100%">
</p>

<p align="center">
  <strong>Connecting donors, patients, and hospitals through transparent, hospital-verified blood donation coordination.</strong>
</p>

<p align="center">
  <a href="https://github.com/alimemonnn/BloodLink/actions/workflows/ci.yml">
    <img src="https://github.com/alimemonnn/BloodLink/actions/workflows/ci.yml/badge.svg" alt="GitHub Actions tests">
  </a>
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Flask-3.0-black?logo=flask" alt="Flask">
  <img src="https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-4169E1?logo=postgresql&logoColor=white" alt="SQLite and PostgreSQL">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
</p>

<p align="center">
  <a href="#-overview">Overview</a> •
  <a href="#-screenshots">Screenshots</a> •
  <a href="#-features">Features</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-testing">Testing</a> •
  <a href="#-deployment">Deployment</a>
</p>

---

## 📌 Overview

**BloodLink** is a Flask-based web application designed to improve coordination between blood donors, patients or their families, and hospitals.

Traditional emergency blood coordination often relies on phone calls and messaging groups. BloodLink provides a centralized workflow in which patients submit requests, hospitals review those requests, compatible volunteer donors can offer assistance, and hospitals verify completed donations.

The central principle is simple:

> **Donor willingness is not a confirmed donation. Only hospital-verified donations count toward fulfilling a request.**

BloodLink is a university software engineering project. It is not a medical service, does not determine clinical eligibility, and does not replace professional blood-bank procedures.

### 🎯 The problem BloodLink addresses

- Coordinating multiple donors for a single blood request.
- Tracking required, pledged, confirmed, and remaining units separately.
- Preventing unverified donor offers from being counted as completed donations.
- Giving patients, donors, and hospitals role-specific workflows.
- Maintaining a traceable history of requests, offers, and hospital confirmations.

## 📸 Screenshots

The following screenshots showcase the main workflows and interface.

### Hospital coordination and messaging

<p align="center">
  <img src="docs/screenshots/hospital-donor-coordination.png" alt="Hospital donor coordination" width="100%">
</p>

<p align="center">
  <img src="docs/screenshots/chat-thread-patient.png" alt="Conversation between a donor, patient family, and hospital" width="100%">
</p>

### Donor dashboard and QR check-in

<p align="center">
  <img src="docs/screenshots/donor-dashboard.png" alt="Donor dashboard with availability, badges, and eligibility countdown" width="100%">
</p>

<p align="center">
  <img src="docs/screenshots/qr-checkin-donor.png" alt="Donor QR check-in code" width="70%">
</p>

### Mobile experience

<p align="center">
  <img src="docs/screenshots/chat-thread-mobile.png" alt="BloodLink mobile chat interface" width="280">
</p>

### Public blood stock and analytics

<p align="center">
  <img src="docs/screenshots/public-stock.png" alt="Public hospital blood stock page" width="100%">
</p>

<p align="center">
  <img src="docs/screenshots/admin-analytics.png" alt="Administrative analytics dashboard" width="100%">
</p>

> Screenshot paths are relative to the repository root. Keep the filenames and directory structure consistent with the files in `docs/screenshots/`.

---

## ✨ Features

### 🩸 1. Hospital-verified donation tracking

BloodLink distinguishes between four important quantities:

| Metric | Meaning |
|---|---|
| Required units | Total units requested by the patient |
| Pledged units | Units associated with active donor offers |
| Confirmed units | Units recorded through hospital-confirmed donations |
| Remaining units | Required units minus confirmed units, with a minimum of zero |

Request progress is calculated from verified donation records rather than a manually maintained counter.

For example, if a patient requires three units:

```text
Required units: 3

Donor A offers 1 unit
Pledged: 1 | Confirmed: 0

Hospital confirms Donor A
Confirmed: 1 | Remaining: 2 | Progress: 33%

Hospital confirms Donor B
Confirmed: 2 | Remaining: 1 | Progress: 66%

Hospital confirms Donor C
Confirmed: 3 | Remaining: 0 | Progress: 100%
```

The application calculates remaining units and progress dynamically.

### 🔒 2. Request integrity and transaction safety

Server-side rules help protect donation records and request totals:

- Only the hospital responsible for a request can confirm its donations.
- A donor's offer represents willingness to help, not medical approval or completed donation.
- Confirmation cannot exceed the required number of units.
- Duplicate confirmation attempts are rejected.
- Database transactions protect related updates.
- PostgreSQL row locking helps prevent concurrent users from claiming the same remaining unit.
- Outstanding offers are cancelled when a request is fulfilled, cancelled, or expired.
- A consistency-check command helps identify disagreements between request states and donation records.

### 🤝 3. Rule-based donor matching

The matching system in `utils/matching.py` uses transparent rules rather than machine learning.

**Hard filters include:**
- Configured ABO/Rh red-cell compatibility.
- Active donor account and declared availability.
- Configurable rest interval.
- Hospital-recorded deferral status.
- Whether the donor has already responded to the request.

**Ranking can consider:**
- City and available location information.
- Exact blood-group match.
- Donation history and other configured matching factors.

The system explains why a donor appears in the shortlist. Matching is intended to support hospital coordination, not replace professional screening, testing, or crossmatching.

### 💬 4. Private coordination chat

Once a donor offers to help, a conversation is associated with that donation response.

- Communication between the donor, patient or family, and hospital.
- Automatic timeline entries for relevant coordination events.
- Appointment and donation-plan information.
- Quick replies for common coordination messages.
- Optional one-time location sharing with configurable retention.
- Urdu and Sindhi right-to-left message display.
- Rate limiting and HTML escaping.
- Chat history included in relevant data-export workflows.
- Message retention and account-deletion handling.

Chat messages do not change donation totals or request states directly. Delivery uses short polling rather than a WebSocket server.

### 👥 5. Role-based workflows

| Role | Main capabilities |
|---|---|
| Patient / family | Register, submit requests, view progress, review offers, receive updates, cancel requests, and manage personal data |
| Donor | Manage availability, review compatible requests, offer assistance, track donation history, and control contact-sharing preferences |
| Hospital | Approve or reject requests, coordinate donors, schedule appointments, record eligibility decisions, confirm donations, and close requests |
| Administrator | Verify hospitals, manage accounts, view analytics and activity logs, and handle privacy requests and contact messages |

### 🚀 6. Additional capabilities

| Area | Features |
|---|---|
| Emergency coordination | Configurable escalation for urgent requests and compatible donors |
| Trust and verification | QR check-in, no-show records, donation certificates, and public certificate verification |
| Notifications | Configurable email, SMS, WhatsApp, push notifications, and appointment reminders |
| Account security | Email confirmation, password-reset links, optional two-factor authentication, and recovery codes |
| Request assistance | Rule-based form assistance from pasted messages and rule-based scam or money-request flagging |
| Translation | Optional English, Urdu, and Sindhi translation through the Claude API |
| Hospital tools | Public blood stock, donation camps, sign-ups, analytics, and CSV export |
| Donor engagement | Badges, donation streaks, and next-eligible-date countdown |
| Data access | Account data export, deletion workflows, privacy requests, and retention cleanup |
| Platform | REST API documentation, database migrations, structured logging, optional Redis rate limiting, and optional Sentry integration |

**External integrations:** SMS, WhatsApp, push notifications, translation, Redis, and Sentry require appropriate configuration. Automated tests using fakes do not establish that a live third-party integration is operational.

---

## 🧭 Request lifecycle

```mermaid
flowchart TD
    A[Patient submits blood request] --> B{Hospital reviews request}
    B -->|Rejected| C[Request rejected]
    B -->|Approved| D[Request opened]
    D --> E[Compatible donors can offer help]
    E --> F[Hospital contacts and schedules donors]
    F --> G{Hospital verifies donation}
    G -->|Not eligible| H[Record ineligibility]
    H --> E
    G -->|Donation confirmed| I[Update confirmed units]
    I --> J{Request fully fulfilled?}
    J -->|No| E
    J -->|Yes| K[Mark fulfilled and cancel leftover offers]
```

### Request states

Requests can progress from pending hospital approval to open, partially fulfilled, and fulfilled. Rejected, cancelled, and expired states are also supported.

### Donor-response states

Responses can progress through interested, contacted, appointment scheduled, and donation completed. Cancellation and ineligibility are alternative outcomes.

---

## 🏗️ Architecture

BloodLink uses a Python Flask application with a relational database, server-rendered templates, and modular business logic.

```text
BloodLink/
├── app.py                 # Application setup, security and CLI commands
├── config.py              # Environment-driven configuration
├── models/                # Database models
├── routes/                # Public, authentication and role-specific routes
├── utils/
│   ├── allocation.py      # Donation totals and allocation rules
│   ├── matching.py        # Compatibility filters and ranking
│   ├── notifications.py   # Notification workflows
│   ├── mailer.py          # Email delivery
│   ├── privacy.py         # Privacy-related workflows
│   ├── maintenance.py     # Maintenance and retention tasks
│   └── ...                # Validation, authentication and rate limiting
├── templates/             # Jinja2 HTML templates
├── static/                # CSS, JavaScript and self-hosted assets
├── tests/                 # Automated test suite
├── docs/                  # Architecture, setup and compliance documentation
├── scripts/               # Supporting scripts
├── requirements.txt
├── requirements-dev.txt
├── render.yaml
└── README.md
```

### Technology stack

| Layer | Technology |
|---|---|
| Language | Python |
| Web framework | Flask 3 |
| ORM and database | Flask-SQLAlchemy, SQLAlchemy 2 |
| Databases | SQLite for development; PostgreSQL for production and database testing |
| Templates | Jinja2 |
| Frontend | HTML, CSS, JavaScript, Bootstrap 5 |
| Charts and icons | Chart.js, Font Awesome Free |
| Migrations | Alembic through Flask-Migrate |
| Testing | pytest |
| Production hosting configuration | Render with an external PostgreSQL database |

Frontend assets are self-hosted, according to the project documentation.

### Does BloodLink use AI?

BloodLink currently combines rule-based automation and analytics. Its compatibility filtering, ranking, form assistance, and scam-flagging features are rule-based. Dashboard charts aggregate database records.

The optional translation feature uses an external language-model API. **BloodLink does not claim to have a trained machine-learning model for donor matching or demand forecasting.**

---

## 🔐 Security, privacy, and responsible use

The project includes features intended to support safer handling of personal information:

- Role-based and object-level authorization.
- CSRF protection and security-related HTTP headers.
- Configurable secure cookies and HTTPS-related production settings.
- Explicit consent records and policy-version tracking.
- Restricted display of patient and donor contact information.
- Account data export and deletion workflows.
- Configurable data retention and cleanup.
- Rate limiting and audit logging.
- Notification deduplication and reduced exposure of sensitive details.
- Self-hosted frontend assets and a configured Content Security Policy.

Read `docs/COMPLIANCE_CHECKLIST.md` for the project's compliance checklist and remaining actions.

> **Important:** These are implemented project features, not a certification of regulatory compliance or proof of security against every attack. Policies require appropriate legal review, and the application requires further operational and security validation before real-world use.

---

## ⚙️ Installation

### Prerequisites

- Python 3.12 recommended for the documented setup.
- Git.
- A terminal or VS Code.
- A supported database configuration.

### 1. Clone the repository

```bash
git clone https://github.com/alimemonnn/BloodLink.git
cd BloodLink
```

### 2. Create and activate a virtual environment

**Windows CMD:**

```bat
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements-dev.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and configure the values required by your environment.

At minimum, the application configuration requires:

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=your-database-connection-string
```

Production configuration also requires the documented administrator credentials and other applicable settings.

**Never commit real secrets, SMTP credentials, database passwords, API keys, or production environment files to GitHub.**

### 5. Prepare demo data

For an empty local development database:

```bash
python seed.py
```

The seed script is intended for local demonstration data. It refuses to seed a database that already contains data and refuses to run in production. Review its behavior before using any reset option.

### 6. Start the application

```bash
python app.py
```

Open:

`http://127.0.0.1:5000`

For VS Code setup and debugging, see [`docs/VSCODE.md`](docs/VSCODE.md).

---

## 🧪 Testing

BloodLink includes automated tests for application workflows, database behavior, and core business rules.

Run the test suite locally:

```bash
python -m pytest -q
```

The repository also includes original workflow test scripts:

```bash
python test_workflows.py
python test_new_features.py
```

Check donation-record consistency:

```bash
flask --app app check-consistency
```

### Database testing

SQLite is used for local development and testing. PostgreSQL is also covered by the GitHub Actions workflow.

For PostgreSQL testing, configure a dedicated test database and set `TEST_DATABASE_URL` to its connection string before running the suite.

Example for Bash:

```bash
export TEST_DATABASE_URL="postgresql://user:password@localhost:5432/bloodlink_test"
python -m pytest -q
```

Example for Windows CMD:

```bat
set TEST_DATABASE_URL=postgresql://user:password@localhost:5432/bloodlink_test
python -m pytest -q
```

Use a disposable test database, not a production database.

### Continuous integration

The GitHub Actions workflow in `.github/workflows/ci.yml` is configured to run SQLite and PostgreSQL test jobs on pushes and pull requests. It also includes a PostgreSQL migration check.

See [GitHub Actions](https://github.com/alimemonnn/BloodLink/actions) for the actual status of the latest run.

---

## 🗄️ Database migrations

BloodLink supports database schema management through Flask-Migrate and Alembic.

Upgrade a database managed by migrations:

```bash
flask --app app db upgrade
```

Generate a migration after a model change:

```bash
flask --app app db migrate -m "Describe the schema change"
```

For a database created outside the migration history, `flask db stamp head` may be appropriate only after verifying that the existing schema matches the expected migration state.

### Before upgrading an existing database

1. Back up the database or take a provider snapshot.
2. Review the migration and application configuration.
3. Apply the migration using the appropriate database URL.
4. Run the test suite and `check-consistency`.
5. Verify the result before using the upgraded application.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for further technical details.

---

## ☁️ Deployment

The repository includes Render deployment configuration in `render.yaml`. The documented production architecture uses Flask with PostgreSQL.

### Production configuration

Configure the following values in your hosting provider's environment settings:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Application signing and security |
| `DATABASE_URL` | Database connection |
| `ADMIN_EMAIL` | Initial or configured administrator email |
| `ADMIN_PASSWORD` | Administrator credential configuration |
| `PUBLIC_BASE_URL` | Public application URL, where required |
| `BUSINESS_EMAIL` | Contact information shown in applicable pages and policies |

Additional variables enable optional integrations. See `.env.example` and `docs/EMAIL_SETUP.md`.

### Background and maintenance jobs

The application provides commands for background tasks and retention cleanup:

```bash
flask --app app jobs
flask --app app retention-cleanup
```

Configure a suitable schedule for the tasks in your production environment. The repository documents a five-minute job schedule in `render.yaml`; verify the actual hosting configuration before relying on it.

### Before a public launch

- Use a managed PostgreSQL database with appropriate access controls.
- Set strong production secrets and administrator credentials.
- Configure real email and any required notification providers.
- Run database migrations and verify backups.
- Test password reset and email verification against real accounts.
- Review authorization, privacy, retention, and incident-response procedures.
- Confirm that scheduled jobs execute successfully.
- Remove demo credentials and test data from any public environment.

---

## 🔧 Environment variables and optional integrations

The complete variable list is maintained in `.env.example`. Important optional integrations include:

| Setting | Purpose |
|---|---|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Email delivery |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and related settings | SMS and WhatsApp through Twilio |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Web push notifications |
| `ANTHROPIC_API_KEY` | Optional translation integration |
| `REDIS_URL` | Shared rate limiting across workers |
| `SENTRY_DSN` | Optional error reporting |
| `LOG_FORMAT=json` | Structured JSON logging |
| `REQUIRE_2FA_ROLES` | Require two-factor authentication for configured roles |
| `USE_ALEMBIC=1` | Enable migration-managed schema setup |

Refer to the environment example and setup documentation for required values, defaults, and provider-specific instructions.

---

## ⚠️ Known limitations

BloodLink is an evolving university project. The following limitations should be understood before deployment or real-world use:

- It is not a medical device or medical service.
- Blood compatibility and donor eligibility must be verified by qualified professionals; configurable application rules are not clinical guidance.
- Live third-party integrations must be tested with authorized accounts. Passing tests using fakes does not verify live provider behavior.
- Location ranking uses available location data and does not provide live traffic or route optimization.
- Urdu and Sindhi translations are drafts and need native-speaker review.
- QR scanning depends on browser capabilities; manual short-code entry is available where supported by the application.
- Public blood-stock information may be self-reported and out of date.
- Privacy policies need legal review before real-world operation.
- Chat uses polling rather than WebSockets or server-sent events.
- Accessibility automation does not replace testing with real assistive-technology users.
- Hosting availability, database persistence, email delivery, and scheduled tasks depend on the actual production configuration.

---

## 🛣️ Future work

Potential next steps include:

- Live-provider integration testing and monitoring.
- Full interface translation and native-speaker review.
- Real-time messaging with WebSockets or server-sent events.
- More granular hospital staff permissions.
- Blood-bank-reviewed donor screening workflows.
- Volunteer transport coordination.
- A mobile application wrapper.
- Evidence-based demand forecasting, if reliable historical data and a suitable evaluation baseline become available.

These are proposed improvements, not claims about currently implemented functionality.

---

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome.

1. Review [`CONTRIBUTING.md`](CONTRIBUTING.md).
2. Check the existing issues before opening a duplicate.
3. Create a feature branch for your changes.
4. Add or update tests for behavioral changes.
5. Run the test suite before submitting a pull request.
6. Never include secrets, real patient information, or production data in commits or tests.

For security-related concerns, see [`SECURITY.md`](SECURITY.md).

## 📄 License

BloodLink is released under the MIT License. See [`LICENSE`](LICENSE) for the complete license text.

---

<p align="center">
  <strong>BloodLink</strong><br>
  <sub>A university project focused on transparent coordination, verified donation records, and responsible software design.</sub>
</p>
