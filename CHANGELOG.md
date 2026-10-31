# Changelog

## Unreleased: care, camps and themes
* Donors can read why they are deferred and their hospital health check reports (PDF). Hospitals write them (shared or private).
* "I donated" claims for the hospital to verify; hospital emergency requests; donation camps with waiting list, edit, roster and recorded donations (camp certificates); camp reminders.
* Three themes (Light, Dark, Classic) with a navbar picker; accessibility checks pass on all three. Migration `0002`.

## Earlier: advanced platform
* Chat: timeline events, donation plan card, quick replies, one-time location sharing, Urdu/Sindhi text, money/link flagging, optional Translate.
* Matching: distance, "available now", no-show history. Automatic escalation of unanswered urgent requests.
* Trust: QR check-in, no-show record, certificate PDF and public verification.
* Alerts: SMS, WhatsApp, email and web push through a queue and a cron job; appointment reminders; installable app (PWA).
* Accounts: password reset, email confirmation, two-factor login with recovery codes.
* Hospitals: blood stock, donation camps, analytics, CSV export. Donors: badges, streaks, camps.
* Platform: public API + OpenAPI, Alembic migrations, Redis rate limiting, JSON logs + request ids, Sentry, Urdu/Sindhi interface, accessibility fixes.

## Earlier
* Hospital-verified multi-donor allocation, consent and privacy tooling, admin tools, first chat release.
