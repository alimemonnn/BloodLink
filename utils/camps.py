"""Donation camps: sign-up with a waiting list, edits, attendance, donations recorded by the hospital, reminders."""
from datetime import date, datetime, timedelta

from flask import current_app

from models import BloodStock, Camp, CampSignup, db
from utils import allocation
from utils.matching import BLOOD_GROUPS
from utils.notifications import notify_donor

ACTIVE = ("Signed up", "Attended", "Donated")


class CampError(Exception):
    pass


def local_now():
    """"Now" on the clock people type camp times with (UTC plus LOCAL_UTC_OFFSET_MINUTES)."""
    return datetime.utcnow() + timedelta(minutes=current_app.config.get("LOCAL_UTC_OFFSET_MINUTES", 0))


ROSTER_OPENS_BEFORE = timedelta(hours=2)


def add_to_stock(hospital_id, blood_group, units):
    """A donation recorded at a camp goes straight into the hospital's blood stock. Returns the new total or None."""
    if blood_group not in BLOOD_GROUPS or units < 1:
        return None
    row = BloodStock.query.filter_by(hospital_id=hospital_id, blood_group=blood_group).first()
    if row is None:
        row = BloodStock(hospital_id=hospital_id, blood_group=blood_group, units=0)
        db.session.add(row)
    row.units = min((row.units or 0) + units, 9999)
    row.updated_at = datetime.utcnow()
    return row.units


def parse_dt(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def validate(form, require_future=True):
    """Return (clean values, problems) for the create and edit forms."""
    errors = []
    title, venue, city = (form.get("title") or "").strip(), (form.get("venue") or "").strip(), (form.get("city") or "").strip()
    starts, ends = parse_dt(form.get("starts_at")), parse_dt(form.get("ends_at"))
    try:
        cap = int(form.get("capacity") or 0)
    except ValueError:
        cap = 0
    if not 5 <= len(title) <= 140:
        errors.append("The title must be 5 to 140 characters.")
    if not venue or len(venue) > 200:
        errors.append("Enter the venue (up to 200 characters).")
    if not city or len(city) > 80:
        errors.append("Enter the city.")
    if starts is None or ends is None:
        errors.append("Enter valid start and end times.")
    elif require_future and starts < local_now():
        errors.append("The camp must start in the future.")
    elif ends <= starts or ends - starts > timedelta(days=7):
        errors.append("The end must be after the start and within 7 days.")
    if not 1 <= cap <= 5000:
        errors.append("Capacity must be between 1 and 5000.")
    return dict(title=title, venue=venue, city=city, starts_at=starts, ends_at=ends, capacity=cap,
                description=(form.get("description") or "").strip()[:600] or None), errors


def _open(camp):
    return not camp.is_cancelled and camp.ends_at >= local_now()


def join(camp, donor):
    if not _open(camp):
        raise CampError("That camp is not open for sign-up.")
    if CampSignup.query.filter_by(camp_id=camp.id, donor_id=donor.id).first():
        raise CampError("You are already signed up.")
    status = "Signed up" if camp.spots_left > 0 else "Waitlist"
    signup = CampSignup(camp_id=camp.id, donor_id=donor.id, status=status)
    db.session.add(signup)
    db.session.commit()
    return signup


def leave(camp_id, donor):
    signup = CampSignup.query.filter_by(camp_id=camp_id, donor_id=donor.id).first()
    if signup is None:
        return None
    if signup.status in ("Attended", "Donated"):
        raise CampError("You already attended this camp, so it cannot be cancelled.")
    camp, held_a_place = signup.camp, signup.status == "Signed up"
    db.session.delete(signup)
    db.session.flush()
    if held_a_place:
        promote(camp)
    db.session.commit()
    return True


def promote(camp):
    """Give free places to people on the waiting list, in the order they joined, and tell them."""
    db.session.refresh(camp)
    promoted = []
    while camp.spots_left > 0 and camp.waitlist:
        s = camp.waitlist[0]
        s.status = "Signed up"
        notify_donor(s.donor_id, f"A place opened at \"{camp.title}\" on {camp.starts_at:%d %b}. You are signed up now.",
                     dedupe_key=f"camp-promote:{camp.id}:{s.donor_id}", commit=False)
        db.session.flush()
        db.session.refresh(camp)
        promoted.append(s)
    return promoted


def update(hospital, camp, form):
    if camp.hospital_id != hospital.id:
        raise CampError("That camp was not found.")
    if camp.is_cancelled:
        raise CampError("A cancelled camp cannot be edited.")
    clean, errors = validate(form, require_future=False)
    if errors:
        raise CampError(" ".join(errors))
    changed = [k for k in ("starts_at", "ends_at", "venue", "city") if getattr(camp, k) != clean[k]]
    for k, v in clean.items():
        setattr(camp, k, v)
    db.session.flush()
    promote(camp)                                   # a bigger capacity frees places
    if changed:
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        for s in camp.signups:
            if s.status in ("Signed up", "Waitlist"):
                notify_donor(s.donor_id, f"\"{camp.title}\" was updated: {camp.venue}, {camp.city}, {camp.starts_at:%d %b at %H:%M}.",
                             dedupe_key=f"camp-edit:{camp.id}:{s.donor_id}:{stamp}", commit=False)
        for s in camp.signups:
            s.reminded_at = None                     # send the 24-hour reminder again for the new time
    allocation.audit("hospital", hospital.id, "camp.edit", "camp", camp.id)
    db.session.commit()
    return changed


def record(hospital, signup_id, action, units=None):
    """The hospital's roster: attended, donated (with units) or no-show."""
    signup = db.session.get(CampSignup, signup_id)
    if signup is None or signup.camp.hospital_id != hospital.id:
        raise CampError("That sign-up was not found.")
    camp = signup.camp
    if camp.is_cancelled:
        raise CampError("This camp was cancelled.")
    if signup.status == "Waitlist":
        raise CampError("This person is still on the waiting list.")
    if camp.starts_at - local_now() > ROSTER_OPENS_BEFORE:
        raise CampError(f"The roster opens 2 hours before the camp, at {camp.starts_at - ROSTER_OPENS_BEFORE:%d %b %H:%M}.")
    if signup.status == "Donated":
        raise CampError("This donation is already recorded.")
    now = datetime.utcnow()
    if action == "attended":
        signup.status, signup.checked_in_at = "Attended", signup.checked_in_at or now
    elif action == "no_show":
        if signup.status == "Attended":
            raise CampError("This donor already arrived.")
        signup.status = "No-show"
        db.session.flush()
        promote(camp)
    elif action == "donated":
        cap = current_app.config["MAX_UNITS_PER_DONOR_DONATION"]
        try:
            n = int(units or 1)
        except ValueError:
            n = 0
        if not 1 <= n <= cap:
            raise CampError(f"Units must be between 1 and {cap}.")
        signup.status, signup.units = "Donated", n
        signup.checked_in_at = signup.checked_in_at or now
        signup.verified_at, signup.verified_by_hospital_id = now, hospital.id
        signup.donor.last_donation_date = now.date()
        add_to_stock(hospital.id, signup.donor.blood_group, n)          # camp blood joins the stock automatically
        allocation.audit("hospital", hospital.id, "stock.camp_add", "hospital", hospital.id,
                         f"+{n} {signup.donor.blood_group} from camp #{camp.id}")
        notify_donor(signup.donor_id, f"Thank you! Your donation at \"{camp.title}\" was recorded. Open My donations for your certificate.",
                     dedupe_key=f"camp-donated:{signup.id}", commit=False)
    else:
        raise CampError("Unknown action.")
    allocation.audit("hospital", hospital.id, f"camp.{action}", "camp_signup", signup.id)
    db.session.commit()
    return signup


def donor_donations(donor):
    return (CampSignup.query.filter_by(donor_id=donor.id, status="Donated")
            .order_by(CampSignup.verified_at.desc()).all())


def stats(camp):
    by = {}
    for s in camp.signups:
        by[s.status] = by.get(s.status, 0) + 1
    return {"signed": by.get("Signed up", 0) + by.get("Attended", 0) + by.get("Donated", 0), "waiting": by.get("Waitlist", 0),
            "attended": by.get("Attended", 0) + by.get("Donated", 0), "donated": by.get("Donated", 0),
            "units": sum(s.units for s in camp.signups), "no_show": by.get("No-show", 0)}


def send_reminders(now=None):
    """24 hours before a camp, remind everyone who has a place. Once per sign-up."""
    from utils import channels
    now = now or local_now()
    n = 0
    rows = (CampSignup.query.join(Camp, CampSignup.camp_id == Camp.id)
            .filter(CampSignup.status == "Signed up", CampSignup.reminded_at.is_(None), Camp.is_cancelled.is_(False),
                    Camp.starts_at > now, Camp.starts_at <= now + timedelta(hours=24)).all())
    for s in rows:
        camp = s.camp
        text = f"Reminder: \"{camp.title}\" is on {camp.starts_at:%d %b at %H:%M} at {camp.venue}, {camp.city}. Bring a photo ID."
        key = f"camp-remind:{s.id}:{camp.starts_at:%Y%m%d%H%M}"
        notify_donor(s.donor_id, text, dedupe_key=key, commit=False)
        channels.alert_donor(s.donor, text, key, "Donation camp reminder")
        s.reminded_at = now
        n += 1
    db.session.commit()
    return n


def ics(camp):
    from utils.chat import _ics_escape
    fmt = "%Y%m%dT%H%M%S"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BloodLink//Donation camp//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
             f"UID:bloodlink-camp-{camp.id}-{camp.starts_at.strftime(fmt)}@bloodlink", f"DTSTAMP:{datetime.utcnow().strftime(fmt)}Z",
             f"DTSTART:{camp.starts_at.strftime(fmt)}", f"DTEND:{camp.ends_at.strftime(fmt)}",
             f"SUMMARY:{_ics_escape(camp.title)}", f"LOCATION:{_ics_escape(camp.venue + ', ' + camp.city)}",
             f"DESCRIPTION:{_ics_escape('Organised by ' + camp.hospital.hospital_name + '. Bring a photo ID.')}",
             "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"
