# BloodLink — Blood Donor & Emergency Request Network

**Connecting Donors, Saving Lives.**

BloodLink is a Flask web application that links patients who need blood, hospitals that
verify those needs, volunteer donors, and an administrator who oversees the platform.
A request only reaches donors after the named hospital has confirmed it is genuine.

Built as a university Software Engineering project. No paid APIs or services are used.

---

## Technology

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3 (custom design system), JavaScript, Bootstrap 5, Font Awesome, Chart.js |
| Backend | Python 3, Flask (blueprints + application factory) |
| Database | **PostgreSQL** in production, SQLite for local development, both through SQLAlchemy ORM |
| Auth | Flask sessions, Werkzeug password hashing, role-based access control, CSRF tokens, login rate limiting |
| Hosting | gunicorn on Render, Neon PostgreSQL (see *Deployment*) |

---

## Installation

You need Python 3.8 or newer.

```bash
# 1. Go into the project folder
cd BloodLink

# 2. Create a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create the database and load demo data
python seed.py

# 5. Run the application
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

To run it from VS Code: open the folder, select the `venv` interpreter, then run `app.py`.

---

## Deployment (live website with a real database)

The app reads one environment variable, `DATABASE_URL`. If it is missing the app uses a
local SQLite file; if it is set the app uses that PostgreSQL database. Nothing else in the
code changes between your laptop and the live site.

**Why not SQLite on the server?** Free hosts wipe the server's disk on every deploy or
restart, so a SQLite file would lose every user. PostgreSQL lives on its own server and
keeps the data.

### 1. Create the database (Neon, free, does not expire)
1. Sign up at neon.tech and create a project.
2. Copy the **connection string** (it starts with `postgresql://`).

### 2. Push the code to GitHub
`.gitignore` already keeps `database.db` and `.env` out of the repository.

### 3. Deploy on Render
1. Render dashboard -> **New +** -> **Blueprint** -> choose the repository (it reads `render.yaml`).
   Or create a **Web Service** manually with build command `pip install -r requirements.txt`
   and start command `gunicorn app:app --workers 2 --timeout 60`.
2. Set these environment variables:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string |
| `SECRET_KEY` | any long random text (the Blueprint generates it) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | your first admin login. It is created automatically on first start, so no default password is ever public |

3. The tables are created automatically on first start. Open the Render URL.

### 4. Optional: demo data on the live database
```bash
# from your laptop, with the live connection string
DATABASE_URL="postgresql://..." python seed.py --force
```
`--force` is required because `seed.py` erases every table first. Do this **once**, before
real users sign up. The seeded demo accounts use the passwords listed above, so remove or
change them after the demo.

### Before the demo
Render's free web service sleeps after 15 minutes without visitors and takes about a
minute to wake up. Open the site a few minutes before presenting.

---

## "Find a donor" flow

1. `/find-blood` shows eight blood-group tiles. Each tile shows how many donors could help
   right now (numbers only, no personal data).
2. A visitor who is **not logged in** and clicks a group sees a login / register page.
   The chosen group is remembered, so after logging in or registering they land directly on
   that group's donor list.
3. Logged-in users see every **compatible** donor (a patient who needs A+ sees A+, A-, O+
   and O- donors), sorted: ready to donate now, then nearest city, then exact group.
   "Exact group only" is one click away.
4. Patients, hospitals and admins see Call / WhatsApp buttons for donors who are ready.
   Donors browsing the list do not see other donors' phone numbers. Set
   `SHOW_DONOR_CONTACT_TO_REQUESTERS = False` in `config.py` to hide numbers for everyone.

---

## Demo accounts

`python seed.py` creates these accounts. Choose the matching account type on the login page.

| Role | Email | Password |
|---|---|---|
| Admin | admin@bloodlink.com | Admin123 |
| Hospital | civil@sukkurhospital.com | Hospital123 |
| Hospital | contact@rohrigh.com | Hospital123 |
| Donor | ahmed.ali@example.com | Donor123 |
| Donor | m.hassan@example.com | Donor123 |
| Patient | rizwan@example.com | Patient123 |
| Patient | ayesha@example.com | Patient123 |

All twelve seeded donors use `Donor123`, all patients use `Patient123`, and all hospitals
use `Hospital123`. Passwords are hashed before they are stored.

Re-running `python seed.py` wipes the database and rebuilds this demo data.

---

## Request workflow

```
Patient registers
   -> Patient posts a blood request        status: Pending Hospital Approval
   -> Hospital reviews it
        approves                           status: Approved       (visible to donors)
        rejects                            status: Rejected       (hidden)
   -> System finds compatible donors and notifies them
   -> Donor clicks "I can donate"          response: Interested
   -> Patient or hospital contacts the donor
   -> Blood is donated                     status: Fulfilled
```

A request that is still Pending or Approved after 14 days is set to **Expired**
automatically, so donors never see stale requests.

---

## Blood compatibility

Matching uses real whole-blood transfusion rules, defined once in `utils/matching.py`:

| Donor group | Can donate to |
|---|---|
| O− | every group (universal donor) |
| O+ | O+, A+, B+, AB+ |
| A− | A−, A+, AB−, AB+ |
| A+ | A+, AB+ |
| B− | B−, B+, AB−, AB+ |
| B+ | B+, AB+ |
| AB− | AB−, AB+ |
| AB+ | AB+ only |

For a request, the system inverts this table to find every group that can supply the
patient, then keeps only donors who are **active**, **available** and **eligible**
(at least 90 days since their last donation). Results are sorted so that donors in the
same city (the typed location or the hospital's city) with an exact group match appear first.

Example — a **B+** request in **Sukkur** matches B+, B−, O+ and O− donors, with Sukkur
donors listed above donors from Rohri or Larkana.

---

## Features by role

**Admin** — dashboard totals and a donors-by-group chart; manage donors (search by name,
blood group, city and availability; edit, activate/deactivate, delete); manage patients;
add, edit, verify, deactivate and delete hospitals; filter all requests by status, blood
group, urgency and city; change a request's status or delete fake ones; reports page with
donors and requests per blood group, requests per city, status breakdown and monthly
donations.

**Donor** — dashboard with blood group, availability, eligibility and response counts;
one-click availability toggle; a feed of approved requests that accept their blood group,
filtered by city and urgency; "I can donate" responses; response history where they update
each response to Interested, Contacted, Donation Completed or Cancelled; in-app
notifications; profile editing and password change.

**Patient** — dashboard counters; post a request naming a verified hospital; edit a request
while it is still pending; track status; see donor responses with contact details; mark a
request fulfilled; cancel a request; profile editing and password change.

**Hospital** — dashboard with pending, approved, critical and fulfilled counts; review each
request; approve (which publishes it to donors and notifies them) or reject; toggle the
verification flag and record verification notes; mark a request fulfilled; view responding
donors and the full list of matching donors with contact details.

---

## Project structure

```
BloodLink/
├── app.py                  # application factory, blueprints, error handlers
├── config.py               # secret key, database URI, business rules
├── seed.py                 # creates the database and demo data
├── test_workflows.py       # 61 automated checks of the main workflows
├── test_new_features.py    # 36 checks: login gate, compatibility list, CSRF, rate limit
├── Procfile, render.yaml   # deployment
├── requirements.txt
├── README.md
│
├── models/                 # SQLAlchemy models
│   ├── __init__.py         # db object and status constants
│   ├── user.py             # Admin
│   ├── donor.py            # Donor + eligibility rules
│   ├── patient.py          # Patient
│   ├── hospital.py         # Hospital
│   └── blood_request.py    # BloodRequest, DonationResponse, Notification
│
├── routes/                 # one blueprint per area
│   ├── public.py           # home, about, how it works, find blood, emergency, contact
│   ├── auth.py             # login, logout, registration for all roles
│   ├── donor.py
│   ├── patient.py
│   ├── hospital.py
│   └── admin.py
│
├── utils/
│   ├── matching.py         # compatibility table and donor matching
│   ├── validators.py       # form validation
│   ├── notifications.py    # database-backed notifications
│   ├── auth.py             # session helpers, @role_required
│   ├── maintenance.py      # automatic request expiry
│   └── ratelimit.py        # login brute-force protection
│
├── templates/              # Jinja2 templates
│   ├── base.html, dashboard_base.html, _macros.html
│   ├── index.html, about.html, how_it_works.html, find_blood.html,
│   │   emergency.html, contact.html
│   ├── auth/, donor/, patient/, hospital/, admin/, errors/
│
└── static/
    ├── css/style.css
    ├── js/script.js
    └── images/
```

---

## Database tables

| Table | Key fields |
|---|---|
| `admins` | id, name, email, password_hash, created_at, last_login_at |
| `donors` | id, name, email, phone, password_hash, blood_group, city, area, last_donation_date, availability, eligibility_status, is_active, created_at, last_login_at |
| `patients` | id, name, email, phone, password_hash, city, address, created_at, last_login_at |
| `hospitals` | id, hospital_name, email, phone, address, city, password_hash, is_verified, is_active, created_at, last_login_at |
| `blood_requests` | id, patient_id, hospital_id, patient_name, blood_group_required, units_required, urgency, location, contact_number, description, status, hospital_verified, hospital_notes, created_at, updated_at, expiry_date |
| `donation_responses` | id, donor_id, request_id, response_status, response_date, donation_date |
| `notifications` | id, donor_id, request_id, message, is_read, created_at |

`donation_responses` has a unique constraint on `(donor_id, request_id)`, so a donor
cannot respond to the same request twice even if the form is submitted repeatedly.

`last_login_at` is new: it is stamped automatically every time an account signs in
successfully, and is what powers the admin "All users" page below. It was added with
an additive, non-destructive migration (`_migrate_schema()` in `app.py`) that runs on
startup and only ever adds the column if it is missing -- it never drops a table or
touches existing rows, so upgrading an already-deployed database is safe.

---

## Admin: "All users" dashboard

`/admin/users` (linked from the top of the admin dashboard) lists every donor,
patient, hospital and admin account in one place:

* Name, account type, email, city
* **Registered at** -- from `created_at`
* **Last active** -- from `last_login_at`, or "Never logged in" if the account has
  never signed in
* Active/inactive status, and a link through to that account's own detail page
* Searchable by name/email and filterable by account type

**What it deliberately does not show: passwords.** Passwords are hashed with
`werkzeug.security.generate_password_hash` the moment an account registers, and the
plaintext is never stored anywhere -- not even the application itself can recover it.
An admin screen that displayed "the password" would either be showing a useless hash
or would require storing passwords in plain text, which this project's own brief
explicitly rules out. If an admin needs to help a user who is locked out, the correct
tool is a password-reset flow (not built in this pass), not password recovery.

---

## Security

1. Passwords are hashed with Werkzeug (`generate_password_hash`) and never stored in plain text.
2. Every form is validated on the server in `utils/validators.py`.
3. Every dashboard route is wrapped in `@role_required(...)`, so a logged-in donor cannot open the admin, hospital or patient pages by typing the URL.
4. Ownership is checked on top of the role: a hospital can only act on requests naming it, and a patient can only open their own requests.
5. All database access goes through SQLAlchemy ORM, which parameterises queries and prevents SQL injection.
6. Login failures give the same message for a wrong email and a wrong password, so the form cannot be used to discover registered emails.
7. Blood groups, phone numbers, emails and dates are validated against fixed rules; a last donation date in the future is rejected.
8. Session cookies are HttpOnly, SameSite=Lax and Secure (HTTPS only) in production. The app refuses to start in production without a `SECRET_KEY`.
9. Deactivated accounts are logged out and cannot sign back in.
10. Hospitals cannot log in until an admin verifies them.
11. **CSRF protection**: every POST form carries a per-session token, so another website cannot trick a logged-in user into approving, cancelling or fulfilling requests.
12. **Brute-force protection**: 5 wrong passwords for one email from one address locks logins for 10 minutes (HTTP 429).
13. **Abuse prevention**: a patient can post at most 5 requests per hour.
14. **Open-redirect protection**: the post-login redirect only accepts in-site paths.
15. Text length limits are checked in the validators, so oversized input shows a form error instead of crashing PostgreSQL.
16. Security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`), logout is POST-only, and passwords must be 8+ characters.
17. The donor directory is not public: donor names and locations are shown only to logged-in users.
18. The admin "All users" page (`/admin/users`) never displays password hashes or any password data, and is covered by a test that scans every account's `password_hash` to confirm it never leaks into the page HTML.

---

## Demo script for the presentation

1. **Home page** — show the live statistics and the emergency requests section.
2. **Donor registration** — register a donor with blood group **O+** in Sukkur.
3. **Patient request** — log in as `rizwan@example.com`, post a **B+**, Critical request at Sukkur Civil Hospital. Point out the status: *Pending Hospital Approval*.
4. **Donor view** — log in as a donor and show the request is **not** listed yet.
5. **Hospital approval** — log in as `civil@sukkurhospital.com`, open the request, add a verification note, approve. The flash message reports how many donors were notified.
6. **Matching** — on the same page, show the matching donors table: B+, B−, O+ and O− donors, Sukkur first.
7. **Donor response** — log back in as the donor; the request now appears and the notification bell has a badge. Click **I can donate**. Click it again to show the duplicate response is blocked.
8. **Patient view** — the patient sees the donor's name and phone number under responses.
9. **Fulfilment** — the hospital marks the request **Fulfilled**; refresh the donor feed to show it has disappeared.
10. **Admin** — log in as the admin: dashboard totals, donor search by blood group, hospital verification, and the reports page charts.

---

## Running the tests

```bash
python test_workflows.py
python test_new_features.py
```

`test_new_features.py` (47 checks) covers the pick-a-group -> login -> results flow, the
compatible-donor list, redirect safety, CSRF, login rate limiting, input limits, request
expiry, the posting limit, `DATABASE_URL` handling, and the admin "All users" page
(access control, last-login timestamping, search/filter, and confirming no password
data ever appears in its HTML). `test_workflows.py` runs 61 checks covering blood compatibility, the matching engine, role-based access
control, login rules, the full request workflow, duplicate-response prevention, editing
rules, eligibility updates, the admin panel and registration validation. It uses a separate
`test_database.db` and leaves your demo database untouched.

Both suites currently pass in full: **108/108 checks**.

**Also add the Postgres/SQLite persistence note if you deploy on Render's free tier:**
if `DATABASE_URL` is not set, the app falls back to a local SQLite file. That file lives
on the web service's own disk, which is **not persistent on Render's free tier** -- it
is wiped on every redeploy and on every cold start after the service spins down from
inactivity. If data (registrations, requests) appears to "disappear" after some time in
a Render deployment, this is almost always why. Set `DATABASE_URL` to a real Postgres
connection string (Neon/Supabase, both have a free tier) for anything you need to
persist across a demo period.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'flask'`** — the virtual environment is not active. Activate it and re-run `pip install -r requirements.txt`.

**Pages look unstyled** — Front-end libraries are bundled in `static/vendor`; no internet is needed for styling.

**`Refusing to run: this would ERASE the database`** — `DATABASE_URL` points at a real database. Unset it for local work, or add `--force` if you really mean it.

**"No verified hospitals are registered yet"** on the request form — log in as admin and verify a hospital, or add one from *Hospitals → Add hospital*.

**Starting over** — delete `database.db` and run `python seed.py` again.

---

## Known limitations

- Notifications are in-app only (no SMS / WhatsApp / email sending).
- "Nearest" means the same city; there is no GPS or map distance.
- The login rate limiter is in memory, so it is per server process. A large deployment would use Redis.
- Front-end libraries and fonts are bundled in `static/vendor`, so the site works offline.
- A request goes live to donors only after the hospital approves it. This prevents fake requests, but it adds a step in a real emergency; hospitals should keep their dashboard open.
- The free Render server sleeps when idle and the first visit afterwards takes about a minute.
- Admins cannot see or reset a user's forgotten password (by design -- passwords are one-way hashed). A self-service "forgot password" email flow and an admin-triggered password reset are natural next additions but are not built in this pass.
