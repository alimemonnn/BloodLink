# Audit report (original project, before changes)

Inspected: every file in `app.py`, `config.py`, `models/`, `routes/`, `utils/`, all templates, JS, CSS, `seed.py`, tests,
`render.yaml`, `Procfile`, `.gitignore`, the bundled vendor assets and the supplied SQLite database.
Baseline: the app started and the 61 + 47 original script checks passed.

## Existing features that worked
Role-based login (4 roles), registration with hashing, CSRF tokens, login rate limiting, hospital verification,
approval workflow, compatibility table (correct for red cells), notifications for donors, admin CRUD, analytics,
expiry housekeeping, security headers, PostgreSQL/SQLite switch, self-hosted assets.

## Critical bugs and gaps found
| # | Finding | Impact |
|---|---|---|
| 1 | **Multi-donor requests did not work.** `units_required` was stored but never used; the first confirmed donor marked the whole request *Fulfilled*; a patient or the hospital could set *Fulfilled* with one click. | The teacher's 3-unit scenario failed. |
| 2 | **Donors could self-report "Donation Completed"** (`/donor/history/<id>/update`), which also reset their eligibility. | Unauthorised donation claims. |
| 3 | Patient "cancel" hard-deleted the request. | No history, orphaned responses. |
| 4 | Nothing derived "pledged / confirmed / remaining". No audit trail of who verified a donation. | No accountability. |
| 5 | No race protection on confirmation. | Possible double counting. |
| 6 | `seed.py` ran `db.drop_all()` on whatever database it found, and the README told users to `--force` it on the live database. | Data-loss risk. |
| 7 | Schema upgrades relied on `create_all()`; no safe migration for new columns. | Breaks existing databases. |

## Privacy and compliance problems
Public home/emergency pages showed **patient full names**; the login page claimed details are "never shown to the public".
Donor phone/email (and WhatsApp links) were shown to every patient/hospital without the donor's consent. The contact form
**discarded messages** while promising a reply, with a fake email/phone. No privacy policy, terms, refund, cookie policy,
consent records, age confirmation, deletion/export, or retention. Unneeded data (patient home address) collected.
Claims such as "one donation can support up to three patients" were unsupported.

## Accessibility and UX problems
Auto-scrolling ticker and infinite pulse animations, count-up numbers that show "0" without JS, alerts that vanish after
6 s, amber focus ring (2.8:1), success-green text 3.8:1, white-on-light Bootstrap badges, decorative icons read by screen
readers, no skip link, charts without text alternatives, missing autocomplete tokens, preselected "Available".

## Other
`venv/`, `database.db`, `__pycache__` and unrelated coursework (`task1.py`, `MuhammadAli_0880_AI_lab/`) were inside the
project. Unrelated coursework was removed from the repository (keep it in a separate private folder). No CDN or tracker was found.

## Prioritised plan (all implemented unless stated)
1. Multi-donor allocation + locking + audit. 2. Close self-claim / one-click-fulfil routes. 3. Safe migration + backup.
4. Privacy by design (initials, consent-gated contact, minimisation). 5. Policies, consent, cookie notice, deletion/export.
6. Accessibility and contrast. 7. Tests (pytest) and docs. *Not done:* ML forecasting (no real data), maps/GPS, SMS.
