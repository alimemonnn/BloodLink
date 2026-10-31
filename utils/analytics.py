"""Numbers for the admin and hospital reports. Nothing here contains a name, phone or email."""
import csv
import io
import statistics
from collections import Counter
from datetime import datetime

from sqlalchemy import func

from utils.matching import BLOOD_GROUPS

from models import (OPEN_STATUSES, STATUS_FULFILLED, BloodRequest, DonationResponse,
                    Donor, RESP_COMPLETED, db)


def csv_safe(value):
    """Stop spreadsheet formula injection: a cell that starts with = + - @ is shown as text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(header, rows):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for row in rows:
        w.writerow([csv_safe(c) for c in row])
    return out.getvalue()


def _hours(a, b):
    return max(0.0, (b - a).total_seconds() / 3600)


def fulfilment_times(hospital_id=None):
    """Hours from approval to the last confirmed donation, for every fulfilled request."""
    q = BloodRequest.query.filter_by(status=STATUS_FULFILLED)
    if hospital_id:
        q = q.filter_by(hospital_id=hospital_id)
    out = []
    for req in q:
        done = [r.verified_at for r in req.responses if r.response_status == RESP_COMPLETED and r.verified_at]
        if done:
            start = req.approved_at or req.created_at
            out.append(_hours(start, max(done)))
    return out


def fulfilment_stats(hospital_id=None):
    times = fulfilment_times(hospital_id)
    return {"fulfilled": len(times),
            "average_hours": round(statistics.mean(times), 1) if times else None,
            "median_hours": round(statistics.median(times), 1) if times else None}


def response_stats(hospital_id=None):
    q = db.session.query(DonationResponse)
    if hospital_id:
        q = q.join(BloodRequest, DonationResponse.request_id == BloodRequest.id) \
             .filter(BloodRequest.hospital_id == hospital_id)
    offers = q.count()
    completed = q.filter(DonationResponse.response_status == RESP_COMPLETED).count()
    no_shows = q.filter(DonationResponse.no_show_at.isnot(None)).count()
    attended_or_missed = completed + no_shows
    return {"offers": offers, "completed": completed, "no_shows": no_shows,
            "completion_rate": round(100 * completed / offers) if offers else None,
            "no_show_rate": round(100 * no_shows / attended_or_missed) if attended_or_missed else None}


def demand_supply():
    """Units still needed on open requests versus donors who could come, per blood group."""
    need = Counter()
    for req in BloodRequest.query.filter(BloodRequest.status.in_(OPEN_STATUSES)):
        need[req.blood_group_required] += req.units_remaining
    supply = dict(db.session.query(Donor.blood_group, func.count(Donor.id)).filter(
        Donor.is_active.is_(True), Donor.availability == "Available",
        Donor.eligibility_status == "Eligible").group_by(Donor.blood_group))
    return [{"group": g, "units_needed": need.get(g, 0), "donors_available": supply.get(g, 0)}
            for g in BLOOD_GROUPS]


def city_demand_supply(limit=10):
    need = Counter()
    for req in BloodRequest.query.filter(BloodRequest.status.in_(OPEN_STATUSES)):
        need[(req.location or "").strip().title() or "Unknown"] += req.units_remaining
    supply = Counter()
    for city, n in db.session.query(Donor.city, func.count(Donor.id)).filter(
            Donor.is_active.is_(True), Donor.availability == "Available").group_by(Donor.city):
        supply[(city or "").strip().title() or "Unknown"] += n
    cities = [c for c, _ in (need + supply).most_common(limit)]
    return [{"city": c, "units_needed": need.get(c, 0), "donors_available": supply.get(c, 0)} for c in cities]


def escalation_counts():
    return {"escalated": BloodRequest.query.filter(BloodRequest.escalation_level > 0).count(),
            "level_2": BloodRequest.query.filter(BloodRequest.escalation_level >= 2).count()}


def request_rows(hospital_id=None):
    """One anonymous line per request (no patient, donor or contact details)."""
    q = BloodRequest.query
    if hospital_id:
        q = q.filter_by(hospital_id=hospital_id)
    rows = []
    for r in q.order_by(BloodRequest.id):
        done = [x.verified_at for x in r.responses if x.response_status == RESP_COMPLETED and x.verified_at]
        hours = round(_hours(r.approved_at or r.created_at, max(done)), 1) if r.status == STATUS_FULFILLED and done else ""
        rows.append([r.id, r.blood_group_required, r.units_required, r.units_confirmed, r.urgency, r.location,
                     r.status, r.escalation_level or 0, r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "", hours])
    return rows


REQUEST_HEADER = ["request_id", "blood_group", "units_required", "units_confirmed", "urgency", "city",
                  "status", "escalation_level", "created_utc", "hours_to_fulfil"]
