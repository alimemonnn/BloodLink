# BloodLink — Blood Donor & Emergency Request Network

**Connecting blood donors, patients, and hospitals through a coordinated blood-donation platform.**

BloodLink is a Flask-based web application that helps patients request blood, connects them with compatible volunteer donors, and enables hospitals to review requests and verify donations.

> **Disclaimer:** BloodLink is a university project, not a medical service. Hospitals and qualified medical professionals remain responsible for donor eligibility, testing, crossmatching, and donation decisions.

## Features

- **Role-based accounts:** Separate interfaces for donors, patients, hospitals, and administrators.
- **Blood requests:** Submit requests with blood group, required units, urgency, hospital, and deadline.
- **Donor matching:** Rule-based blood compatibility filtering and explainable donor ranking.
- **Hospital verification:** Hospitals approve requests, coordinate donors, and confirm completed donations.
- **Donation tracking:** Track required, pledged, confirmed, and remaining units.
- **Private messaging:** Coordinate between donors, patients, and hospitals.
- **Notifications:** Optional email, SMS, WhatsApp, and web push integrations.
- **Security and privacy:** Authentication, consent records, access controls, account data export and deletion, and audit logs.
- **Hospital tools:** Blood-stock listings, donation camps, QR check-in, certificates, and analytics.
- **Multilingual interface:** English, Urdu, and Sindhi support.
- **Installable web app:** PWA and push-notification support where configured.

## How It Works

1. A patient submits a blood request.
2. A hospital reviews and approves or rejects the request.
3. Compatible donors can express interest in an approved request.
4. The hospital coordinates appointments and professional screening.
5. The hospital confirms completed donations.
6. BloodLink updates the confirmed units and request status.

Donation progress is based on hospital-confirmed records, not unverified donor claims.

## Technology Stack

| Component | Technologies |
|---|---|
| Backend | Python, Flask |
| Database | SQLite for development; PostgreSQL for production |
| ORM and migrations | Flask-SQLAlchemy, SQLAlchemy, Flask-Migrate, Alembic |
| Frontend | HTML, CSS, JavaScript, Bootstrap 5, Jinja2 |
| Charts | Chart.js |
| Testing | pytest |
| Deployment | Gunicorn, environment-based configuration |
| Optional services | Redis, SMTP, Twilio, web push, Sentry |

Donor matching uses transparent, rule-based logic. BloodLink does not currently claim to use machine learning for donor matching.

## Project Structure

```text
BloodLink/
├── app.py
├── config.py
├── models/
├── routes/
├── utils/
├── templates/
├── static/
├── migrations/
├── tests/
├── docs/
├── requirements.txt
├── requirements-dev.txt
├── seed.py
└── render.yaml
```

## Getting Started

### Requirements

- Python 3.12
- Git
- A virtual environment

### Installation

```bash
git clone https://github.com/alimemonnn/BloodLink.git
cd BloodLink

python -m venv venv
```

On Windows:

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Configure the required environment variables using `.env.example` as a reference. Then initialize the database as appropriate for your environment and run:

```bash
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

### Database Migrations

For a database managed by Alembic:

```bash
flask --app app db upgrade
```

Back up existing data before applying schema changes. Never run demo-data reset commands against a production database.

### Testing

```bash
python -m pytest
```

The project also includes workflow tests and a database consistency check:

```bash
flask --app app check-consistency
```

## Configuration

See `.env.example` for the available settings.

Important production variables include:

- `SECRET_KEY` — application session and security key.
- `DATABASE_URL` — database connection string.
- `ADMIN_EMAIL` and `ADMIN_PASSWORD` — initial administrator configuration, if required by the application.
- `PUBLIC_BASE_URL` — public application URL.
- `BUSINESS_EMAIL` — contact address shown to users.

Optional integrations can be configured for email, notifications, rate limiting, error monitoring, and translation.

**Never commit secrets, database credentials, real user information, or production passwords to GitHub.**

## Deployment

BloodLink requires a hosted Flask backend and a PostgreSQL database for a shared online service.

The repository includes a `render.yaml` configuration for Render. Deployment requires the appropriate environment variables, database migrations, and background-job scheduling.

For a public deployment:

- Configure HTTPS and secure production settings.
- Keep database credentials and application secrets private.
- Configure and verify scheduled jobs.
- Test account permissions, authentication, backups, and data recovery.
- Verify notification providers before enabling them.
- Do not expose real donor or patient records until the application has been reviewed and secured.

Free hosting services may have usage limits, sleep periods, and restricted background-job support.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Compliance Checklist](docs/COMPLIANCE_CHECKLIST.md)
- [Contributing Guidelines](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [License](LICENSE)

## Known Limitations

- Donor eligibility rules are configurable placeholders and require review by qualified blood-bank professionals.
- Optional third-party integrations require separate configuration and live testing.
- Blood-stock information may be outdated if hospitals do not update it.
- Urdu and Sindhi translations require native-speaker review.
- Privacy policies and compliance documentation require appropriate legal review before real-world use.
- A successful technical deployment does not establish clinical suitability or operational readiness.

## Contributing

Contributions are welcome. Please read `CONTRIBUTING.md` and `SECURITY.md` before submitting changes or reporting security vulnerabilities.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
