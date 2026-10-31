# Compliance and trust checklist (20 points)

Status key: **Done** = implemented and covered by an automated test · **You** = needs a decision or input from you.
This is an engineering checklist, **not legal advice**. Have a lawyer review the policy text before real use.

| # | Item | Status | What was done / where |
|---|---|---|---|
| 1 | Privacy policy | Done | `/privacy` (`templates/legal/privacy.html`): data table per role, who sees what, retention periods that match the code, rights, children, security. |
| 2 | Terms of service | Done | `/terms`: not a medical service, 18+, hospital decides eligibility, no payment for blood, acceptable use, liability, governing law (Pakistan, edit if wrong). |
| 3 | Refund policy | Done | `/refund-policy`: the service is free, nothing to refund, how to report anyone charging in BloodLink's name, hospital charges are separate. |
| 4 | Cookie policy | Done | `/cookies`: table of the only 2 cookies (`session`, `bl_consent`), purpose, lifetime. |
| 5 | Cookie consent banner | Done | `_cookie_banner.html` + `static/js/consent.js`: non-blocking, keyboard accessible, equal-weight buttons, reopenable from the footer, `BloodLinkConsent.allowed()` gate for any future optional cookie. No optional cookies exist, and the banner says so. |
| 6 | Form consents | Done | Registration: unticked, required Terms+Privacy, 18+, donor health-data consent; optional contact-sharing and email (separate, unticked). Contact and data-request forms need a consent tick. Donor "I can donate" requires a per-request sharing tick. Every consent stored in `consent_records` with policy version and time; withdrawable in profile. |
| 7 | Don't collect unnecessary data | Done | Removed patient home address (form, profile, admin edit). No DOB/ID/GPS/gender. Optional area and last-donation date marked optional. Public pages show patient **initials only**; donors never see patient name/phone/notes; donor phone/email hidden unless consented. Retention job anonymises old requests. |
| 8 | Audit third-party SDKs | Done | None are used for analytics/ads/social. Every script, style, font and icon is self-hosted; CSP (`default-src 'self'`) blocks anything else; a test fails if a template loads an external resource. The only outbound links are user-initiated (`wa.me` WhatsApp button, only for consenting donors; Font Awesome licence page). Table in `/licenses`. |
| 9 | Remove dark patterns | Done | Removed: pulsing "ready right now" claim, "live" ping dots, auto-scrolling ticker, count-up from 0, auto-vanishing alerts, preselected "Available", unsupported urgency copy. Added: equal-weight cookie buttons, deletion as easy as sign-up, `prefers-reduced-motion`. |
| 10 | Remove hidden fees | Done | There were none; now stated explicitly in Terms and Refund policy; test fails if fee/"pay" wording appears. |
| 11 | Remove fake reviews | Done | None existed; a test blocks testimonial/rating wording. Homepage numbers are live database counts (no animation from 0). |
| 12 | Remove unsupported claims | Done | Removed "one donation can support up to three patients", "every donor who can safely give it", "partner hospitals", "never shown to the public" (it was false), "we will reply" (messages were discarded), fake phone/email on the contact page, "SQLite / runs locally" mismatch. Added medical disclaimers. |
| 13 | Accessibility alt text | Done | No raster images exist (logo is inline SVG). Decorative icons `aria-hidden`, charts `role="img"` + `aria-label` + data table, progress bars have `aria-valuetext`, tables have captions/scopes. Test fails on any `<img>` without `alt`. |
| 14 | Keyboard navigation | Done | Skip link, `<main>` focus target, visible dark focus ring (light on dark areas), keyboard-operable radios/menus/banner, Esc closes the banner, no timing traps. |
| 15 | Colour contrast | Done | All text/background token pairs ≥ 4.5:1 and focus ring ≥ 3:1, enforced by `tests/test_compliance.py`. Fixed: success green (3.84→≥4.5), amber focus ring (2.77→dark ring), light badges now dark text. |
| 16 | Business details | **You** | Footer, Contact, policies read `BUSINESS_*` env vars. Name/operator/location are filled from your project; **set `BUSINESS_EMAIL`** (and phone/registration if you have them). Nothing is invented; a visible note appears on policy pages until the email is set. |
| 17 | Age consent for kids' data | Done | Donor/patient accounts require an "I am 18+" confirmation (no DOB stored). A request naming a patient under 18 requires a parent/guardian confirmation (`guardian_confirmed_at`). Policy explains this. |
| 18 | Unsubscribe link in emails | Done | `utils/mailer.py`: opt-in only, signed one-click unsubscribe link + `List-Unsubscribe` headers, nothing sent without a working link, failures swallowed. App sends no email until you configure SMTP (**You**). |
| 19 | License fonts and images | Done | Licence texts in `static/vendor/licenses/` (SIL OFL 1.1 ×2, Font Awesome Free, MIT ×2) + `/licenses` page with attribution. No stock images are used; the logo is original. |
| 20 | Data deletion request option | Done | Self-service: *Profile → Delete my account* (password + type DELETE) erases personal data, anonymises what must stay (verified unit counts). Public `/data-request` form (delete/access/correct) feeds the admin **Privacy inbox**. Export: *Download my data* (JSON). |

## Things only you can do

1. Set `BUSINESS_EMAIL` (and `PUBLIC_BASE_URL` if you enable email).
2. Confirm the minimum donation interval and eligibility policy with a real blood bank.
3. Have the policies reviewed by a qualified person; adjust governing law / authority wording to your situation.
4. Check Pakistan-specific obligations for health-related data before collecting real donors' data.
5. Run `flask retention-cleanup` daily in production.
6. Identity verification for public deletion requests is manual (by email) by design.
