"""Blood stock, donation camps, hospital analytics and CSV exports."""
from datetime import datetime, timedelta

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, url_for)
from sqlalchemy import func

from models import (BloodStock, Camp, CampSignup, Donor, Hospital, db)
from utils import analytics, badges, allocation
from utils.matching import BLOOD_GROUPS
from utils.auth import current_user, role_required
from utils.notifications import notify_donor

community_bp = Blueprint("community", __name__)
LOW_STOCK = 2


def _parse_dt(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _ago(when):
    if not when:
        return "never"
    mins = int((datetime.utcnow() - when).total_seconds() // 60)
    if mins < 2:
        return "just now"
    if mins < 120:
        return f"{mins} minutes ago"
    if mins < 60 * 48:
        return f"{mins // 60} hours ago"
    return f"{mins // 1440} days ago"


# ---------------------------------------------------------------- blood stock
@community_bp.route("/hospital/stock", methods=["GET", "POST"])
@role_required("hospital")
def manage_stock():
    hospital = current_user()
    rows = {s.blood_group: s for s in hospital.stock}
    if request.method == "POST":
        values, errors = {}, []
        for g in BLOOD_GROUPS:
            raw = request.form.get(f"units_{g}", "").strip()
            if raw == "":
                continue
            if not raw.isdigit() or int(raw) > 9999:
                errors.append(f"{g}: enter a whole number from 0 to 9999.")
            else:
                values[g] = int(raw)
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            for g, units in values.items():
                if g in rows:
                    if rows[g].units != units:
                        rows[g].units = units
                        rows[g].updated_at = datetime.utcnow()
                else:
                    db.session.add(BloodStock(hospital_id=hospital.id, blood_group=g, units=units))
            db.session.commit()
            flash("Blood stock saved.", "success")
            return redirect(url_for("community.manage_stock"))
    return render_template("community/stock_manage.html", groups=BLOOD_GROUPS, rows=rows, ago=_ago, low=LOW_STOCK)


@community_bp.route("/stock")
def public_stock():
    city = request.args.get("city", "").strip()
    q = Hospital.query.filter_by(is_verified=True, is_active=True)
    if city:
        q = q.filter(func.lower(Hospital.city) == city.lower())
    hospitals = [h for h in q.order_by(Hospital.hospital_name) if h.stock]
    totals = {g: 0 for g in BLOOD_GROUPS}
    for h in hospitals:
        for s in h.stock:
            totals[s.blood_group] += s.units
    cities = sorted({c for (c,) in db.session.query(Hospital.city).filter_by(is_verified=True, is_active=True)})
    return render_template("community/stock_public.html", hospitals=hospitals, totals=totals, groups=BLOOD_GROUPS,
                           city=city, cities=cities, ago=_ago, low=LOW_STOCK)


# --------------------------------------------------------------------- camps
@community_bp.route("/camps")
def camps():
    city = request.args.get("city", "").strip()
    q = Camp.query.filter(Camp.is_cancelled.is_(False), Camp.ends_at >= datetime.utcnow())
    if city:
        q = q.filter(func.lower(Camp.city) == city.lower())
    donor = current_user() if getattr(current_user(), "role", None) == "donor" else None
    joined = {s.camp_id for s in donor.camp_signups} if donor else set()
    return render_template("community/camps.html", camps=q.order_by(Camp.starts_at).limit(100).all(),
                           city=city, joined=joined, donor=donor)


@community_bp.route("/camps/<int:camp_id>/join", methods=["POST"])
@role_required("donor")
def join_camp(camp_id):
    donor, camp = current_user(), db.session.get(Camp, camp_id)
    if camp is None or camp.is_cancelled or camp.ends_at < datetime.utcnow():
        flash("That camp is not open for sign-up.", "warning")
    elif CampSignup.query.filter_by(camp_id=camp.id, donor_id=donor.id).first():
        flash("You are already signed up.", "info")
    elif camp.spots_left <= 0:
        flash("Sorry, this camp is full.", "warning")
    else:
        db.session.add(CampSignup(camp_id=camp.id, donor_id=donor.id))
        db.session.commit()
        flash(f"You are signed up for {camp.title}. Thank you!", "success")
    return redirect(url_for("community.camps"))


@community_bp.route("/camps/<int:camp_id>/leave", methods=["POST"])
@role_required("donor")
def leave_camp(camp_id):
    CampSignup.query.filter_by(camp_id=camp_id, donor_id=current_user().id).delete()
    db.session.commit()
    flash("Your sign-up was cancelled.", "info")
    return redirect(url_for("community.camps"))


@community_bp.route("/hospital/camps", methods=["GET", "POST"])
@role_required("hospital")
def manage_camps():
    hospital = current_user()
    if request.method == "POST":
        f = request.form
        starts, ends = _parse_dt(f.get("starts_at")), _parse_dt(f.get("ends_at"))
        title, venue, city = f.get("title", "").strip(), f.get("venue", "").strip(), f.get("city", "").strip()
        cap = f.get("capacity", type=int) or 0
        errors = []
        if not 5 <= len(title) <= 140:
            errors.append("The title must be 5 to 140 characters.")
        if not venue or len(venue) > 200:
            errors.append("Enter the venue (up to 200 characters).")
        if not city or len(city) > 80:
            errors.append("Enter the city.")
        if starts is None or ends is None:
            errors.append("Enter valid start and end times.")
        elif starts < datetime.utcnow():
            errors.append("The camp must start in the future.")
        elif ends <= starts or ends - starts > timedelta(days=7):
            errors.append("The end must be after the start and within 7 days.")
        if not 1 <= cap <= 5000:
            errors.append("Capacity must be between 1 and 5000.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            camp = Camp(hospital_id=hospital.id, title=title, venue=venue, city=city, starts_at=starts,
                        ends_at=ends, capacity=cap, description=(f.get("description") or "").strip()[:600] or None)
            db.session.add(camp)
            db.session.flush()
            for donor in Donor.query.filter(func.lower(Donor.city) == city.lower(), Donor.is_active.is_(True)).limit(500):
                notify_donor(donor.id, f"Donation camp near you: {title}, {starts:%d %b at %H:%M}. Open Camps to sign up.",
                             dedupe_key=f"camp:{camp.id}:{donor.id}", commit=False)
            allocation.audit("hospital", hospital.id, "camp.create", "camp", camp.id)
            db.session.commit()
            flash("Camp published. Donors in that city were notified.", "success")
            return redirect(url_for("community.manage_camps"))
    mine = Camp.query.filter_by(hospital_id=hospital.id).order_by(Camp.starts_at.desc()).all()
    return render_template("community/camps_manage.html", camps=mine, city=hospital.city)


@community_bp.route("/hospital/camps/<int:camp_id>/cancel", methods=["POST"])
@role_required("hospital")
def cancel_camp(camp_id):
    camp = db.session.get(Camp, camp_id)
    if camp is None or camp.hospital_id != current_user().id:
        abort(404)
    camp.is_cancelled = True
    for s in camp.signups:
        notify_donor(s.donor_id, f"The camp \"{camp.title}\" on {camp.starts_at:%d %b} was cancelled.",
                     dedupe_key=f"camp-cancel:{camp.id}:{s.donor_id}", commit=False)
    allocation.audit("hospital", camp.hospital_id, "camp.cancel", "camp", camp.id)
    db.session.commit()
    flash("Camp cancelled and sign-ups notified.", "info")
    return redirect(url_for("community.manage_camps"))


# ---------------------------------------------------------- hospital analytics
@community_bp.route("/hospital/analytics")
@role_required("hospital")
def hospital_analytics():
    h = current_user()
    return render_template("community/hospital_analytics.html", fulfil=analytics.fulfilment_stats(h.id),
                           responses=analytics.response_stats(h.id))


@community_bp.route("/hospital/analytics/requests.csv")
@role_required("hospital")
def hospital_requests_csv():
    body = analytics.to_csv(analytics.REQUEST_HEADER, analytics.request_rows(current_user().id))
    return Response(body, mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="my-requests.csv"'})


# --------------------------------------------------------------- admin exports
@community_bp.route("/admin/analytics/requests.csv")
@role_required("admin")
def admin_requests_csv():
    body = analytics.to_csv(analytics.REQUEST_HEADER, analytics.request_rows())
    return Response(body, mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="requests.csv"'})


@community_bp.route("/admin/analytics/supply-demand.csv")
@role_required("admin")
def admin_supply_csv():
    rows = [[r["group"], r["units_needed"], r["donors_available"]] for r in analytics.demand_supply()]
    rows += [[f"city:{c['city']}", c["units_needed"], c["donors_available"]] for c in analytics.city_demand_supply(50)]
    body = analytics.to_csv(["blood_group_or_city", "units_needed", "donors_available"], rows)
    return Response(body, mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="supply-demand.csv"'})
