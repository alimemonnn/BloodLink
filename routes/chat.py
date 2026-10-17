"""Chat pages and the small JSON endpoints the page polls.

URLs: /messages (inbox), /messages/<offer id> (thread), plus /admin/chat-reports
for the report queue. Every thread URL re-checks that the logged-in person is a
participant; guessing an id gives a 404 (not a hint that the thread exists).
"""
from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)

from models import ChatReport, DonationResponse, db
from utils import chat
from utils.auth import current_user, login_required, role_required

chat_bp = Blueprint("chat", __name__)

MAX_POLL_BATCH = 200


def _thread_or_404(response_id, allow_admin_with_report=False):
    """Load the offer and the viewer's role in it, or abort(404)."""
    resp = db.session.get(DonationResponse, response_id)
    if resp is None:
        abort(404)
    role, user = session.get("role"), current_user()
    if role == "admin" and allow_admin_with_report and chat.has_reports(resp):
        return resp, "admin", user
    if chat.participant_role(role, user, resp) is None:
        abort(404)
    return resp, role, user


@chat_bp.route("/messages")
@role_required("donor", "patient", "hospital")
def inbox():
    role, user = session["role"], current_user()
    return render_template("chat/inbox.html", threads=chat.threads_for(role, user.id),
                           role=role, base_nav=f"{role}/_nav.html")


@chat_bp.route("/messages/<int:response_id>")
@role_required("donor", "patient", "hospital", "admin")
def thread(response_id):
    resp, role, user = _thread_or_404(response_id, allow_admin_with_report=True)
    msgs = chat.messages_after(resp.id, 0, MAX_POLL_BATCH)
    if role != "admin" and msgs:
        chat.mark_read(resp.id, role, user.id, msgs[-1].id)
    return render_template(
        "chat/thread.html", resp=resp, role=role, can_post=chat.can_post(resp) and role != "admin",
        closed_note=chat.closed_reason(resp), is_admin=(role == "admin"),
        messages=[chat.serialize(m, resp, role, getattr(user, "id", None)) for m in msgs],
        last_id=msgs[-1].id if msgs else 0, base_nav=f"{role}/_nav.html",
        max_len=current_app.config["CHAT_MAX_LENGTH"], plan=chat.plan(resp),
        quick=chat.QUICK_REPLIES.get(role, []), can_share_location=role in chat.LOCATION_ROLES,
        location_hours=current_app.config["CHAT_LOCATION_VISIBLE_HOURS"],
        my_reports=ChatReport.query.filter_by(response_id=resp.id).order_by(ChatReport.id).all()
        if role == "admin" else [])


@chat_bp.route("/messages/<int:response_id>/poll")
@role_required("donor", "patient", "hospital", "admin")
def poll(response_id):
    resp, role, user = _thread_or_404(response_id, allow_admin_with_report=True)
    after = request.args.get("after", 0, type=int) or 0
    msgs = chat.messages_after(resp.id, after, MAX_POLL_BATCH)
    if role != "admin" and msgs:
        chat.mark_read(resp.id, role, user.id, msgs[-1].id)
    return jsonify(
        messages=[chat.serialize(m, resp, role, getattr(user, "id", None)) for m in msgs],
        can_post=chat.can_post(resp) and role != "admin", note=chat.closed_reason(resp),
        plan=chat.plan(resp))


@chat_bp.route("/messages/<int:response_id>/send", methods=["POST"])
@role_required("donor", "patient", "hospital")
def send(response_id):
    resp, role, user = _thread_or_404(response_id)
    wants_json = request.is_json or request.headers.get("X-Requested-With") == "fetch"
    body = (request.get_json(silent=True) or {}).get("body") if request.is_json \
        else request.form.get("body", "")
    try:
        msg = chat.send_message(role, user, resp, body)
    except chat.ChatError as err:
        if wants_json:
            return jsonify(error=str(err)), 400
        flash(str(err), "warning")
        return redirect(url_for("chat.thread", response_id=resp.id))
    if wants_json:
        return jsonify(message=chat.serialize(msg, resp, role, user.id)), 201
    return redirect(url_for("chat.thread", response_id=resp.id) + "#end")


@chat_bp.route("/messages/<int:response_id>/location", methods=["POST"])
@role_required("donor", "patient")
def share_location(response_id):
    """Send the caller's position once. Only the donor and the patient's family may do this."""
    resp, role, user = _thread_or_404(response_id)
    data = request.get_json(silent=True) or {}
    try:
        msg = chat.send_location(role, user, resp, data.get("lat"), data.get("lng"), data.get("accuracy"))
    except chat.ChatError as err:
        return jsonify(error=str(err)), 400
    return jsonify(message=chat.serialize(msg, resp, role, user.id)), 201


@chat_bp.route("/messages/<int:response_id>/appointment.ics")
@role_required("donor", "patient", "hospital")
def appointment_ics(response_id):
    resp, role, user = _thread_or_404(response_id)
    body = chat.calendar_file(resp) if resp.is_active else None
    if body is None:
        abort(404)
    return Response(body, mimetype="text/calendar", headers={
        "Content-Disposition": f'attachment; filename="blood-donation-{resp.request_id}.ics"'})


@chat_bp.route("/messages/<int:response_id>/report", methods=["POST"])
@role_required("donor", "patient", "hospital")
def report(response_id):
    resp, role, user = _thread_or_404(response_id)
    try:
        chat.report(role, user, resp, request.form.get("reason", ""),
                    request.form.get("message_id", type=int))
        flash("Thank you. An administrator will review this conversation.", "success")
    except chat.ChatError as err:
        flash(str(err), "warning")
    return redirect(url_for("chat.thread", response_id=resp.id))


# ----------------------------------------------------------------------
# Administrator: report queue
# ----------------------------------------------------------------------
@chat_bp.route("/admin/chat-reports")
@role_required("admin")
def admin_reports():
    status = request.args.get("status", "Open")
    q = ChatReport.query
    if status in ("Open", "Dismissed", chat.LOCKED):
        q = q.filter_by(status=status)
    return render_template("chat/admin_reports.html", reports=q.order_by(ChatReport.id.desc()).limit(100).all(),
                           status=status, chat_locked=chat.LOCKED)


@chat_bp.route("/admin/chat-reports/<int:report_id>/resolve", methods=["POST"])
@role_required("admin")
def admin_resolve(report_id):
    try:
        chat.resolve_report(report_id, current_user(), request.form.get("action", ""),
                            request.form.get("note"))
        flash("Report updated.", "success")
    except chat.ChatError as err:
        flash(str(err), "warning")
    return redirect(url_for("chat.admin_reports"))
