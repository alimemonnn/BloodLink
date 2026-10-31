"""Installable app files, push subscriptions, and donor alert preferences."""
import json

from flask import (Blueprint, Response, current_app, flash, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)

from models import PushSubscription, db
from utils import geo, privacy
from utils.auth import current_user, login_required, role_required
from utils.validators import checked
from datetime import datetime, timedelta

engage_bp = Blueprint("engage", __name__)


# ------------------------------------------------------------------- PWA files
@engage_bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@engage_bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "BloodLink", "short_name": "BloodLink", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#3a0714", "theme_color": "#c8102e",
        "description": "Find blood donors and coordinate donations with hospitals.",
        "icons": [{"src": "/static/images/pwa/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/images/pwa/icon-512.png", "sizes": "512x512", "type": "image/png",
                   "purpose": "any maskable"}]}
    return Response(json.dumps(data), mimetype="application/manifest+json")


@engage_bp.route("/offline")
def offline():
    return render_template("offline.html")


# ---------------------------------------------------------------------- push
@engage_bp.route("/push/key")
@login_required
def push_key():
    from utils import push
    return jsonify(key=current_app.config["VAPID_PUBLIC_KEY"] if push.is_configured() else "")


@engage_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys") or {}
    endpoint, p256dh, auth = data.get("endpoint", ""), keys.get("p256dh", ""), keys.get("auth", "")
    if not (endpoint.startswith("https://") and len(endpoint) <= 600 and p256dh and auth):
        return jsonify(error="invalid subscription"), 400
    user = current_user()
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh[:200], auth=auth[:100],
                               role=session["role"], user_id=user.id)
        db.session.add(sub)
    else:                                       # same browser, possibly a different account
        sub.role, sub.user_id, sub.p256dh, sub.auth = session["role"], user.id, p256dh[:200], auth[:100]
    db.session.commit()
    return jsonify(ok=True), 201


@engage_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint", "")
    PushSubscription.query.filter_by(endpoint=endpoint, role=session["role"], user_id=current_user().id) \
        .delete(synchronize_session=False)
    db.session.commit()
    return jsonify(ok=True)


# -------------------------------------------------- donor: right now and area
@engage_bp.route("/donor/available-now", methods=["POST"])
@role_required("donor")
def available_now():
    donor = current_user()
    hours = request.form.get("hours", type=int)
    if hours in (2, 6, 12):
        donor.available_until = datetime.utcnow() + timedelta(hours=hours)
        flash(f"Marked as available for the next {hours} hours.", "success")
    else:
        donor.available_until = None
        flash("The \"available now\" mark was removed.", "info")
    db.session.commit()
    return redirect(request.referrer or url_for("donor.dashboard"))


@engage_bp.route("/donor/area", methods=["POST"])
@role_required("donor")
def set_area():
    donor = current_user()
    if request.form.get("clear"):
        donor.area_lat = donor.area_lng = None
        flash("Your approximate area was removed. Your city is used instead.", "info")
    else:
        lat, lng = geo.clean_area(request.form.get("lat"), request.form.get("lng"))
        if lat is None:
            flash("Your position could not be read. Nothing was saved.", "warning")
        else:
            donor.area_lat, donor.area_lng = lat, lng
            privacy.set_consent("donor", donor.id, "approximate_area", True)
            flash("Your approximate area (about 1 km) was saved to rank nearby requests.", "success")
    db.session.commit()
    return redirect(url_for("donor.profile"))
