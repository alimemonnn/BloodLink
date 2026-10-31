"""Donor health pages, hospital screening forms, and the "I donated" check."""
from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, url_for)

from models import (OUTCOMES, REASONS, RESP_COMPLETED, CampSignup, DonationResponse, ScreeningReport, db)
from utils import camps, screening, trust, verification
from utils.auth import current_user, role_required

health_bp = Blueprint("health", __name__)


# --------------------------------------------------------------------- donor
@health_bp.route("/donor/health")
@role_required("donor")
def donor_health():
    donor = current_user()
    donations = []
    for r in donor.responses:
        if r.response_status == RESP_COMPLETED:
            donations.append({"when": r.verified_at or r.response_date, "units": r.units_collected or 1,
                              "where": r.request.hospital.hospital_name, "kind": "Request #%s" % r.request_id,
                              "certificate": url_for("trust.certificate", response_id=r.id)})
    for s in camps.donor_donations(donor):
        donations.append({"when": s.verified_at, "units": s.units or 1, "where": s.camp.hospital.hospital_name,
                          "kind": "Camp: " + s.camp.title, "certificate": url_for("trust.camp_certificate", signup_id=s.id)})
    donations.sort(key=lambda d: d["when"], reverse=True)
    return render_template("health/donor_health.html", donor=donor, eligibility=screening.donor_eligibility(donor),
                           reports=screening.reports_for_donor(donor), donations=donations)


def _own_report(report_id):
    report = db.session.get(ScreeningReport, report_id)
    if report is None or report.donor_id != current_user().id or not report.shared_with_donor:
        abort(404)                      # not yours, or the hospital did not share it: same answer
    return report


@health_bp.route("/donor/health/<int:report_id>")
@role_required("donor")
def donor_report(report_id):
    return render_template("health/report.html", report=_own_report(report_id), labels=screening.LABELS)


@health_bp.route("/donor/health/<int:report_id>.pdf")
@role_required("donor")
def donor_report_pdf(report_id):
    report = _own_report(report_id)
    return Response(screening.report_pdf(report), mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="health-report-{report.id}.pdf"'})


@health_bp.route("/donor/responses/<int:response_id>/claim", methods=["POST"])
@role_required("donor")
def claim(response_id):
    try:
        verification.claim_donation(current_user(), response_id)
        flash("We told the hospital. It will check its records and confirm. Nothing is counted until it does.", "success")
    except verification.ClaimError as err:
        flash(str(err), "warning")
    return redirect(url_for("donor.history"))


# ------------------------------------------------------------------ hospital
def _form(title, donor, back, report, post_url, what):
    return render_template("health/screening_form.html", title=title, donor=donor, back=back, report=report,
                           post_url=post_url, outcomes=OUTCOMES, reasons=REASONS, labels=screening.LABELS, what=what)


@health_bp.route("/hospital/responses/<int:response_id>/screening", methods=["GET", "POST"])
@role_required("hospital")
def screening_response(response_id):
    hospital = current_user()
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.request.hospital_id != hospital.id:
        abort(404)
    back = url_for("hospital.request_detail", request_id=resp.request_id)
    if request.method == "POST":
        data, errors = screening.parse_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return _form("Health check", resp.donor, back, _Draft(request.form), request.path, f"offer for request #{resp.request_id}"), 400
        try:
            screening.save_for_response(hospital, response_id, data)
        except screening.ScreeningError as err:
            flash(str(err), "danger")
            return redirect(back)
        flash("Health check saved." + (" The donor can read it." if data["shared_with_donor"] else " It is private to your hospital."), "success")
        return redirect(back)
    return _form("Health check", resp.donor, back, resp.screening_report, request.path, f"offer for request #{resp.request_id}")


@health_bp.route("/hospital/camps/signups/<int:signup_id>/screening", methods=["GET", "POST"])
@role_required("hospital")
def screening_signup(signup_id):
    hospital = current_user()
    signup = db.session.get(CampSignup, signup_id)
    if signup is None or signup.camp.hospital_id != hospital.id:
        abort(404)
    back = url_for("community.camp_roster", camp_id=signup.camp_id)
    if request.method == "POST":
        data, errors = screening.parse_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return _form("Health check", signup.donor, back, _Draft(request.form), request.path, f"camp \"{signup.camp.title}\""), 400
        screening.save_for_signup(hospital, signup_id, data)
        flash("Health check saved.", "success")
        return redirect(back)
    return _form("Health check", signup.donor, back, signup.screening_report, request.path, f"camp \"{signup.camp.title}\"")


@health_bp.route("/hospital/responses/<int:response_id>/dispute-claim", methods=["POST"])
@role_required("hospital")
def dispute_claim(response_id):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.request.hospital_id != current_user().id:
        abort(404)
    try:
        verification.dispute_claim(current_user(), response_id, request.form.get("note"))
        flash("The donor was told that no donation record was found.", "info")
    except verification.ClaimError as err:
        flash(str(err), "warning")
    return redirect(url_for("hospital.request_detail", request_id=resp.request_id))


class _Draft:
    """Lets the form re-show what the hospital typed after a validation error."""
    def __init__(self, form):
        g = form.get
        self.outcome, self.reason, self.message_to_donor, self.internal_note = g("outcome"), g("reason"), g("message_to_donor"), g("internal_note")
        self.shared_with_donor = g("shared_with_donor") == "on"
        self.deferral_days = g("deferral_days")
        for name in screening.LABELS:
            setattr(self, name, g(name))
        self.deferral_until = None
