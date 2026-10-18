"""Public, read-only JSON API (/api/v1) and its documentation."""
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from models import (OPEN_STATUSES, STATUS_FULFILLED, BloodRequest, Camp, Donor, Hospital, db)
from utils import openapi, ratelimit, trust
from utils.matching import BLOOD_GROUPS

api_bp = Blueprint("api", __name__)
VERSION = "1.0.0"


@api_bp.before_request
def _limit():
    if request.endpoint in ("api.docs", "api.openapi_json"):
        return None
    key = f"api|{request.remote_addr}"
    if ratelimit.is_blocked(key, 60, 60):
        return jsonify(error="Too many requests. Limit: 60 per minute."), 429
    ratelimit.record_failure(key, 60)
    return None


@api_bp.after_request
def _headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"           # public, read-only, no personal data
    response.headers.setdefault("Cache-Control", "public, max-age=30")
    return response


def _page():
    limit = min(max(request.args.get("limit", 20, type=int) or 20, 1), 100)
    offset = max(request.args.get("offset", 0, type=int) or 0, 0)
    return limit, offset


@api_bp.get("/health")
def health():
    return jsonify(status="ok", version=VERSION)


@api_bp.get("/stats")
def stats():
    return jsonify(
        registered_donors=Donor.query.filter_by(is_active=True).count(),
        open_requests=BloodRequest.query.filter(BloodRequest.status.in_(OPEN_STATUSES)).count(),
        partner_hospitals=Hospital.query.filter_by(is_verified=True, is_active=True).count(),
        requests_fulfilled=BloodRequest.query.filter_by(status=STATUS_FULFILLED).count())


@api_bp.get("/requests")
def requests_list():
    q = BloodRequest.query.filter(BloodRequest.status.in_(OPEN_STATUSES))
    if request.args.get("blood_group") in BLOOD_GROUPS:
        q = q.filter_by(blood_group_required=request.args["blood_group"])
    if request.args.get("urgency") in ("Normal", "Urgent", "Critical"):
        q = q.filter_by(urgency=request.args["urgency"])
    city = request.args.get("city", "").strip()
    if city:
        q = q.filter(func.lower(BloodRequest.location).contains(city.lower()))
    limit, offset = _page()
    total = q.count()
    items = q.order_by(BloodRequest.created_at.desc()).offset(offset).limit(limit).all()
    return jsonify(total=total, limit=limit, offset=offset, items=[{
        "id": r.id, "blood_group": r.blood_group_required, "units_remaining": r.units_remaining,
        "urgency": r.urgency, "city": r.location, "hospital": r.hospital.hospital_name, "patient": r.public_label,
        "required_by": r.expiry_date.date().isoformat() if r.expiry_date else None} for r in items])


@api_bp.get("/stock")
def stock():
    q = Hospital.query.filter_by(is_verified=True, is_active=True)
    city = request.args.get("city", "").strip()
    if city:
        q = q.filter(func.lower(Hospital.city) == city.lower())
    items = []
    for h in q.order_by(Hospital.hospital_name):
        if h.stock:
            items.append({"hospital": h.hospital_name, "city": h.city,
                          "updated_at": max(s.updated_at for s in h.stock).isoformat(timespec="minutes"),
                          "units": {s.blood_group: s.units for s in sorted(h.stock, key=lambda s: s.blood_group)}})
    return jsonify(note="Self-reported by hospitals and may be out of date. Call before you travel.", items=items)


@api_bp.get("/camps")
def camps():
    q = Camp.query.filter(Camp.is_cancelled.is_(False), Camp.ends_at >= datetime.utcnow())
    city = request.args.get("city", "").strip()
    if city:
        q = q.filter(func.lower(Camp.city) == city.lower())
    limit, offset = _page()
    total = q.count()
    return jsonify(total=total, limit=limit, offset=offset, items=[{
        "id": c.id, "title": c.title, "hospital": c.hospital.hospital_name, "venue": c.venue, "city": c.city,
        "starts_at": c.starts_at.isoformat(timespec="minutes"), "ends_at": c.ends_at.isoformat(timespec="minutes"),
        "places_left": c.spots_left} for c in q.order_by(Camp.starts_at).offset(offset).limit(limit)])


@api_bp.get("/certificates/<code>")
def certificate(code):
    resp = trust.resolve_certificate(code)
    if resp is None:
        return jsonify(valid=False)
    return jsonify(valid=True, donor=trust.public_name(resp.donor), units=resp.units_collected,
                   date=resp.verified_at.date().isoformat() if resp.verified_at else None,
                   hospital=resp.request.hospital.hospital_name)


@api_bp.get("/openapi.json")
def openapi_json():
    return jsonify(openapi.spec(VERSION))


@api_bp.get("/docs")
def docs():
    return render_template("api_docs.html", spec=openapi.spec(VERSION))
