# BloodLink — Blood Donor & Emergency Request Network

[![tests](../../actions/workflows/ci.yml/badge.svg)](../../actions) ![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.12-blue) ![db](https://img.shields.io/badge/SQLite%20%7C%20PostgreSQL%2016-tested-green)

**Connecting donors, patients and hospitals, with the hospital in charge of every decision that matters.**

BloodLink is a Flask web application. A patient posts a blood request, the named hospital reviews it,
compatible volunteer donors are shown the request and can offer to help, and the hospital coordinates the
donors and **confirms each donation**. A request for several units is tracked until every unit is confirmed.

![BloodLink chat between a donor, a patient's family and the hospital](docs/screenshots/chat-thread-patient.png)

<p>
<img src="docs/screenshots/hospital-donor-coordination.png" width="49%" alt="Hospital coordinates donors and confirms units">
<img src="docs/screenshots/chat-thread-mobile.png" width="22%" alt="Chat on a phone">
</p>

> University project. BloodLink is **not** a medical service. It never decides who may donate or receive
> blood, and it makes no clinical claims. Hospitals decide eligibility, testing and crossmatching.

---

## 1. The problem and the teacher's scenario

*A patient needs three units of blood and three compatible donors are available. How does the system
coordinate them, know how many units have been provided, and know when the request is fulfilled?*

**Answer: totals are derived from hospital-verified donation records, never from donor claims.**

```
required = 3
Donor A offers 1  -> pledged 1, confirmed 0   status Open
Hospital confirms A -> confirmed 1, remaining 2  status Partially Fulfilled   (33 %)
Hospital confirms B -> confirmed 2, remaining 1  status Partially Fulfilled   (66 %)
Hospital confirms C -> confirmed 3, remaining 0  status Fulfilled             (100 %)
```

`remaining = max(0, required - confirmed)` and `progress = min(100, confirmed / required * 100)`;
zero, negative or missing `required` values are handled safely.

### How multi-donor allocation works (`utils/allocation.py`)

| Concept | Where it lives |
|---|---|
| Units **required** | `blood_requests.units_required` (CHECK ≥ 1) |
| One donor's offer / contribution | one row in `donation_responses` per donor per request |
| Units **pledged** (not yet verified) | sum of `units_pledged` of *active* responses (Interested, Contacted, Appointment Scheduled) |
| Units **confirmed** | sum of `units_collected` of responses with status *Donation Completed*. **Only a hospital can set this.** |
| Units **remaining**, **progress %** | computed properties on `BloodRequest`, no stored counter that can drift |

Rules enforced on the **server** (browser checks are only a convenience):

1. Only the hospital that owns the request can confirm a donation (object-level authorisation).
2. A donor's "I can donate" is *willingness only*; it never counts as blood and is not medical approval.
3. A confirmation can never push the total above `required`; by default one unit per donor per event
   (`MAX_UNITS_PER_DONOR_DONATION`).
4. A response can be confirmed once. A retried or double-clicked submit is rejected, not double-counted.
5. The request row is **locked** while confirming (PostgreSQL `SELECT … FOR UPDATE`; on SQLite a no-op write
   takes the single write lock), so two hospital users cannot both claim the last unit. A two-thread test proves it.
6. Everything happens in one transaction; any failure rolls back (also tested).
7. On fulfilment, leftover offers are cancelled and those donors are told. On cancel or expiry, outstanding
   offers are cancelled; verified donations stay on record.
8. `flask check-consistency` verifies that statuses agree with the donation records.

**Request states:** Pending Hospital Approval → Open (stored as `Approved`) → Partially Fulfilled → Fulfilled;
or Rejected / Cancelled / Expired.
**Donor-response states:** Interested → Contacted → Appointment Scheduled → Donation Completed (hospital only);
or Cancelled / Ineligible.

```mermaid
flowchart LR
  P[Patient posts request] --> H{Hospital reviews}
  H -- reject --> R[Rejected]
  H -- approve --> O[Open: donors notified]
  O --> D[Donors offer to help<br/>willingness only]
  D --> C[Hospital contacts / schedules / screens]
  C -- ineligible --> I[Ineligible, optional deferral]
  C -- donation verified --> V[Units confirmed +1]
  V --> Q{confirmed >= required?}
  Q -- no --> PF[Partially Fulfilled]
  PF --> D
  Q -- yes --> F[Fulfilled<br/>leftover offers cancelled]
  O --> X[Cancelled or Expired<br/>offers cancelled, history kept]
```

---

## 2. Donor matching (rule-based, **not** machine learning)

`utils/matching.py`. Hard filters first, then an explainable score that only *orders* what passed.

* **Hard filters (never overridden):** ABO/Rh red-cell compatibility, active account, marked available,
  configurable rest interval since the last donation, not deferred by a hospital, has not already responded.
* **Score (weights in `config.MATCH_WEIGHTS`):** same city, exact blood group, no donation on record. Each match carries
  human-readable reasons shown to the hospital. With no GPS data, proximity is city-level.
* Compatibility is for **red cells / whole blood**; plasma and platelets differ and are not modelled.
* The output is a *shortlist for professional verification*; the hospital screens, tests and crossmatches.

| What | Is it AI? |
|---|---|
| Compatibility table, filters, ranking score | Rule-based automation (transparent, tested) |
| Dashboard counts and charts | Analytics (plain SQL aggregates of real records) |
| Machine learning | **None.** No model is claimed; adding demand forecasting would need real historical data, a baseline and evaluation |

---

## 3. Roles and features

| Role | Can do |
|---|---|
| **Patient / family** | Register (18+), post a request (blood group, units, hospital, urgency, deadline), see approval status, per-request progress (required / pledged / confirmed / remaining), donor offers, updates; cancel with history kept; export or delete their data |
| **Donor** | Register with explicit consents, set availability, see compatible open requests (no patient details), offer to help or cancel an offer, see history and verified donations, choose whether contact details are shared and whether to get email, export or delete their data |
| **Hospital** | Dashboard, approve/reject requests, contact / schedule / screen donors, mark ineligible (with optional deferral), **confirm donations**, close a request with a reason, see who verified what and when |
| **Admin** | Verify hospitals, manage accounts (erasure keeps counts anonymous), database-driven metrics, charts, activity log, **privacy inbox** for data requests and contact messages |

### Chat (donor, patient and hospital)

Once a donor offers to help, a private conversation opens for that one offer. The donor, the patient's family and the
hospital can write; nobody else can read it, and an administrator only after someone **reports** it (admins can then
lock the thread). Chat is for coordination only: it never changes a request or counts blood, and messages never go into
notifications. Delivery is by short polling (about 4 s), which needs no WebSocket server and works on any host.

* **Live timeline.** Hospital and donor actions (offer made, contacted, appointment scheduled, donation confirmed,
  cancelled, request closed) appear in the thread as automatic lines. Screening notes are never copied into chat.
* **Donation plan card.** Hospital name and address, appointment time (updates live), a *Directions* link and an
  *Add to calendar* (.ics) button.
* **Quick replies.** One tap for "I'm on my way", "I've arrived", "Running late", "Thank you" and similar.
* **Share my location (donor and patient only).** Asks for confirmation, sends **one** position, never tracks. The
  hospital can see it, administrators never see coordinates. It is hidden after 6 hours and erased after 24 hours
  (configurable). It opens in Google Maps or OpenStreetMap; no map tiles or third-party scripts are loaded.
* **Urdu and Sindhi.** Messages display right-to-left automatically.
* Patients are shown to donors as initials only. The thread becomes read-only when the offer is cancelled, the request
  closes or the hospital confirms the donation. Messages are rate limited, HTML-escaped, included in data export,
  erased with the account, and deleted 90 days after the request closes.

Notifications are database-backed, deduplicated by key, and never contain patient names or medical details.
Optional email goes only to opted-in donors and always has a one-click unsubscribe.

---

## 4. Privacy, consent and policies (what was added)

Policy pages: `/privacy`, `/terms`, `/refund-policy`, `/cookies`, `/accessibility`, `/licenses`, `/data-request`.
See **[docs/COMPLIANCE_CHECKLIST.md](docs/COMPLIANCE_CHECKLIST.md)** for the full 20-point mapping and the
things *you* must still do (business email, legal review).

Highlights: cookie notice (only 2 first-party necessary cookies, no trackers), unticked consent boxes recorded with
policy version, 18+ confirmation and guardian confirmation for minors' requests, public pages show patient initials
only, donor phone/email shown only with the donor's consent, self-service **export and deletion**, public deletion
request form, retention job, no third-party scripts/fonts (CSP enforced), licence texts shipped.

---

## 5. Technology

Python 3.12 · Flask 3 · Flask-SQLAlchemy / SQLAlchemy 2 · SQLite (dev) / PostgreSQL (prod) · Jinja2 ·
Bootstrap 5 · Chart.js · Font Awesome Free · all assets self-hosted.

```
app.py            application factory, CSP/CSRF, safe additive migration, CLI commands
config.py         settings (env-driven); TestingConfig
models/           Donor, Patient, Hospital, Admin, BloodRequest, DonationResponse, Notification, compliance tables
routes/           public, auth, donor, patient, hospital, admin, legal, account
utils/            allocation (core), matching, notifications, mailer, privacy, maintenance, validators, auth, ratelimit
templates/ static/  UI; static/vendor/licenses holds third-party licence texts
tests/            pytest suite (fake data, temp databases)
docs/             audit report, compliance checklist, presentation guide
```

**Database (schema changes are additive):** new columns on `donors`, `patients`, `hospitals`, `blood_requests`,
`donation_responses`, `notifications`; new tables `consent_records`, `contact_messages`, `data_requests`,
`account_notifications`, `audit_logs`. One response row per donor per request (a cancelled donor re-opens the *same* row).

---

## 6. Install, run, test

```bash
python -m venv venv
venv\Scripts\activate            # Windows      (macOS/Linux: source venv/bin/activate)
pip install -r requirements-dev.txt
python seed.py                   # fake demo data into an EMPTY database
python app.py                    # http://127.0.0.1:5000
python -m pytest                 # automated tests (SQLite)
TEST_DATABASE_URL=postgresql://user:pass@host/db python -m pytest   # same suite on PostgreSQL
python test_workflows.py && python test_new_features.py   # original scripts (also updated)
flask --app app check-consistency   # totals agree with donation records
flask --app app retention-cleanup   # run daily in production
```

`seed.py` refuses to touch a database that already has data (use `python seed.py --reset` and type YES to wipe a
*local* database) and refuses to run in production.

### Environment variables

See `.env.example`. Required in production: `SECRET_KEY`, `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
Recommended: `BUSINESS_EMAIL` (shown in policies and footer), `BUSINESS_PHONE`, `BUSINESS_REGISTRATION`.
Optional email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `PUBLIC_BASE_URL`.

### Upgrading an existing database (safe migration)

1. **Back up first:** copy `database.db` (SQLite) or take a Neon/Supabase snapshot.
2. Replace the code and start the app. `db.create_all()` creates the new tables; `_migrate_schema()` only **adds**
   columns (nullable or with defaults) and back-fills them. It never drops or rewrites a table.
3. On SQLite it also writes `database.db.pre-migration-<timestamp>.bak` before changing anything.
4. Back-fills: completed donations get `units_collected = 1`; old "Open" requests that already had verified donations
   become *Partially Fulfilled*; requests closed by the old one-click flow are flagged `closed_reason='legacy'`
   (their unit records never existed, so they are flagged, not rewritten).
5. Run `flask --app app check-consistency`. Re-running the migration is a harmless no-op.

*Limitation:* new CHECK constraints exist only in freshly created databases (SQLite cannot add them to an existing
table); the same rules are enforced in code. The whole test suite, including the two-thread race tests on the last unit,
also passes on a live PostgreSQL 16 (`TEST_DATABASE_URL`, and the CI workflow runs it on every push).

## 7. Deployment (Render + Neon)

Unchanged in spirit: set `DATABASE_URL`, `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` (+ `BUSINESS_EMAIL`,
`PUBLIC_BASE_URL`); `render.yaml` uses `/healthz` as the health check. Production mode (`RENDER=true` or
`BLOODLINK_ENV=production`) turns on secure cookies, HSTS, proxy headers and refuses to start without a secret key.
Run `flask --app app retention-cleanup` on a daily schedule. Free hosts sleep when idle; open the site before a demo.
Demo data on a live database: run `python seed.py` against an *empty* database **before** setting `ADMIN_EMAIL`.

## 8. Demo accounts (local fake data only)

| Role | Email | Password |
|---|---|---|
| Admin | admin@bloodlink.com | Admin123 |
| Hospital | civil@sukkurhospital.com | Hospital123 |
| Donor | ahmed.ali@example.com | Donor123 |
| Patient | rizwan@example.com | Patient123 |

Delete or change these before any real use. The seed includes a **3-unit O+ request with 2 units already verified**,
so you can confirm the last one live.

## 9. Known limitations

* Not a medical device; eligibility rules (e.g. the 90-day interval) are configurable placeholders to be confirmed by
  a blood bank.
* City-level proximity only; no GPS or map.
* Rate limiting is in-memory per process; use Redis for multiple servers.
* Policies are drafted for this project and are **not legal advice**; have them reviewed before real use.
* Email/SMS are optional and untested against a live provider (provider calls are mocked in tests).
* Not browser-tested visually or audited by an accessibility specialist; contrast is checked numerically.
* Chat uses polling, not WebSockets: simple and host-independent, but messages can take up to about 4 seconds to appear.
* Shared location needs a secure (https) connection and the user's browser permission; the app only ever receives a single snapshot.
* No password-reset or email-verification flow yet (needs an email provider).

## 10. Future work

Demand forecasting (needs real anonymised history + baseline), map/distance ranking, SMS, hospital staff
sub-accounts, two-factor login for hospitals/admin, password reset by email, Redis rate limiting, Alembic migrations, WebSocket/SSE chat.

## 11. Contributing and licence

MIT licensed (see [LICENSE](LICENSE)). Contributions welcome: read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
