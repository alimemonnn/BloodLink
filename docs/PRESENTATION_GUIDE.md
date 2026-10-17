# Presentation guide (about 8–10 minutes)

**1. Problem (1 min).** In an emergency families message dozens of people. Requests are unverified, donors are over- or
under-contacted, and nobody knows how many units have really arrived.

**2. Live demo (4 min).** Log in as patient *Ayesha* → see the seeded **3-unit O+ request: 2 of 3 confirmed, 1 remaining**
(progress bar). Switch to hospital *Sukkur Civil Hospital* → open the request → donor *Bilal* is *Interested* →
**Confirm donation** → request becomes **Fulfilled**. Point out: pledged ≠ confirmed; only the hospital can count blood;
the patient has no confirm button.

**3. How multi-donor coordination works.** One response row per donor per request. Totals are *computed* from verified rows
(no counter to drift). Confirmation runs in one transaction with the request row locked, rejects excess units and repeats.
Say the formula out loud: `remaining = max(0, required − confirmed)`.

**4. How matching works.** Hard filters (ABO/Rh red-cell compatibility, availability, rest interval, deferral, not already
responded) then an explainable score (same city, exact group). Weights are in config. It is a shortlist; the hospital decides.

**5. Why hospital verification is required.** Donor self-reports and patient claims are not medical facts. Eligibility,
screening and crossmatching are clinical decisions. BloodLink records *who* verified *what* and *when*.

**6. What is rule-based vs AI.** Matching/score = rule-based automation. Dashboards = analytics over real records.
**No machine learning is claimed.** A forecast would need real historical data, a baseline model and evaluation metrics.

**7. Security, privacy and testing (1–2 min).** Hashed passwords, CSRF, rate limiting, object-level authorisation, CSP with no
third-party code, consent records, data export/deletion, public pages show initials only. **147 automated tests** including a
two-thread race on the last unit, migration of an old database, and accessibility/contrast checks.

**8. Limitations and future work (1 min).** Not a medical device; city-level distance; in-memory rate limiter; policies need
legal review; forecasting needs real data; PostgreSQL verified by DDL compilation only.

## Questions to expect
* *"What if two nurses confirm at the same time?"* → row lock; the test `test_two_hospital_users_confirming_the_final_unit_simultaneously`.
* *"Why not let donors mark themselves done?"* → that is a claim, not evidence; hospital verification is the control.
* *"Is O-negative always allowed?"* → compatible for red cells, but still filtered by availability, rest interval, deferral and hospital screening.
* *"Where is the AI?"* → be honest: rule-based, explainable; ML is future work with real data.

## Manual acceptance checklist
- [ ] `python seed.py` then `python app.py`; home page loads, cookie notice appears and can be dismissed with the keyboard.
- [ ] Register a donor: submit is blocked until Terms, 18+, health-data boxes are ticked; optional boxes start unticked.
- [ ] Patient posts a 3-unit request; double-click creates one request; it is *Pending* and invisible to donors.
- [ ] Hospital approves; matching donors get a notification; donor feed shows no patient name/phone/notes.
- [ ] Donor offers help (must tick sharing); cancel and re-offer works; a second offer is refused.
- [ ] Hospital contacts, schedules, marks one donor ineligible, confirms three donors: Partial → Partial → Fulfilled.
- [ ] Confirming the same donor twice, or a 4th donor, is refused.
- [ ] Patient cancels another request: donors with offers are notified; history remains.
- [ ] Public home/emergency pages show initials only; find-blood hides phones of non-consenting donors.
- [ ] Profile → Download my data; Delete my account (wrong password refused, DELETE required).
- [ ] `/data-request` creates an item in Admin → Privacy inbox.
- [ ] Tab through the home page: skip link first, visible focus everywhere; OS "reduce motion" stops animation.
- [ ] `python -m pytest` passes; `flask --app app check-consistency` reports consistent.

## Chat demo (add to the live demo, about 45 seconds)

1. Log in as the donor `bilal@example.com` and open **Messages**, then the Request #5 conversation.
2. In a second window log in as the patient `ayesha@example.com` and open the same conversation.
3. Send a message from the donor window. It appears in the patient window within about 4 seconds, with no reload.
4. Say: *only these three parties can read it; the donor sees the patient as initials only; the hospital can join;
   chat can never count blood, only the hospital's Confirm button can; and anyone can report a conversation, after which
   an administrator may read it and lock it.*
5. Optional: type `<b>hello</b>` to show that messages are escaped, not executed.

### Extra 30 seconds: plan card, quick reply and location

6. Point at the **donation plan card** (hospital, appointment, Directions, Add to calendar). Have the hospital change the
   appointment in another window and watch the card and the timeline line update by themselves.
7. Tap a **quick reply** ("I'm on my way") and show it arrive on the patient's screen.
8. Tap **Share my location**. Point out that it asks first, sends one position only, the hospital can see it,
   administrators cannot, and it disappears after 6 hours. (Allow location in the browser; works on https or localhost.)
