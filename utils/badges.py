"""Recognition for donors, computed from hospital-confirmed donations only (never self-reported)."""
from datetime import date, timedelta

from flask import current_app

from models import RESP_COMPLETED

MILESTONES = [(1, "First donation", "fa-droplet"), (3, "3 donations", "fa-hand-holding-droplet"),
              (5, "5 donations", "fa-medal"), (10, "10 donations", "fa-award"), (25, "25 donations", "fa-trophy")]


def _donation_dates(donor):
    dates = []
    for r in donor.responses:
        if r.response_status == RESP_COMPLETED:
            d = r.verified_at.date() if r.verified_at else (r.donation_date or r.response_date.date())
            dates.append((d, r))
    return sorted(dates, key=lambda t: t[0])


def streak(dates, today=None, max_gap_days=366):
    """Donations in a row where each came within a year of the one before; 0 if the last is over a year old."""
    today = today or date.today()
    if not dates or (today - dates[-1]).days > max_gap_days:
        return 0
    run = 1
    for later, earlier in zip(reversed(dates[1:]), reversed(dates[:-1])):
        if (later - earlier).days <= max_gap_days:
            run += 1
        else:
            break
    return run


def summary(donor, today=None):
    today = today or date.today()
    rows = _donation_dates(donor)
    dates = [d for d, _ in rows]
    total_donations = len(rows)
    units = sum((r.units_collected or 1) for _, r in rows)
    badges = [{"name": name, "icon": icon, "earned": total_donations >= n, "need": n}
              for n, name, icon in MILESTONES]
    in_last_year = sum(1 for d in dates if (today - d).days <= 365)
    fast = sum(1 for _, r in rows if r.request and r.request.approved_at and r.response_date
               and 0 <= (r.response_date - r.request.approved_at).total_seconds() <= 3600)
    missed = sum(1 for r in donor.responses if r.no_show_at)
    extra = [
        {"name": "Regular donor", "icon": "fa-rotate", "earned": in_last_year >= 2,
         "hint": "2 donations in the last 12 months"},
        {"name": "Rapid responder", "icon": "fa-bolt", "earned": fast >= 1,
         "hint": "offered help within an hour of a request opening"},
        {"name": "Reliable", "icon": "fa-handshake", "earned": total_donations >= 3 and missed == 0,
         "hint": "3 or more donations and no missed appointments"},
    ]
    gap = current_app.config["DONATION_GAP_DAYS"]
    last = dates[-1] if dates else donor.last_donation_date
    next_date = (last + timedelta(days=gap)) if last else None
    days_left = max(0, (next_date - today).days) if next_date else 0
    return {"donations": total_donations, "units": units, "streak": streak(dates, today),
            "badges": badges, "extra": extra, "next_eligible": next_date if days_left else None,
            "days_left": days_left, "can_donate_now": days_left == 0}
