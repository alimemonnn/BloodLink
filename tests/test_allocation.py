"""Multi-donor allocation: the "3 units, 3 donors" scenario and its edge cases."""
import threading
from datetime import date, datetime, timedelta

import pytest

from conftest import make_donor, make_hospital, make_patient, make_request
from models import (RESP_CANCELLED, RESP_COMPLETED, RESP_INELIGIBLE, RESP_INTERESTED,
                    STATUS_APPROVED, STATUS_CANCELLED, STATUS_EXPIRED, STATUS_FULFILLED,
                    STATUS_PARTIAL, BloodRequest, DonationResponse, Notification, db)
from utils import allocation
from utils.allocation import AllocationError, NotAuthorized
from utils.maintenance import expire_old_requests


def offer(donor, req):
    return allocation.pledge(donor, req.id, 1, consent_to_share=True)


def refresh(req):
    db.session.expire_all()
    return db.session.get(BloodRequest, req.id)


# ----------------------------------------------------------------------
# The teacher's scenario
# ----------------------------------------------------------------------
def test_one_of_three_units_is_partial_not_fulfilled(scene):
    resp = offer(scene.donors[0], scene.request)
    allocation.confirm_donation(scene.hospital, resp.id)
    r = refresh(scene.request)
    assert (r.units_confirmed, r.units_remaining, r.progress_percent) == (1, 2, 33)
    assert r.status == STATUS_PARTIAL


def test_two_of_three_units_still_partial(scene):
    for d in scene.donors[:2]:
        allocation.confirm_donation(scene.hospital, offer(d, scene.request).id)
    r = refresh(scene.request)
    assert (r.units_confirmed, r.units_remaining) == (2, 1)
    assert r.status == STATUS_PARTIAL


def test_three_of_three_units_is_fulfilled(scene):
    for d in scene.donors:
        allocation.confirm_donation(scene.hospital, offer(d, scene.request).id)
    r = refresh(scene.request)
    assert (r.units_confirmed, r.units_remaining, r.progress_percent) == (3, 0, 100)
    assert r.status == STATUS_FULFILLED
    assert r.closed_at is not None


def test_pledges_alone_never_count_as_collected(scene):
    for d in scene.donors:
        offer(d, scene.request)
    r = refresh(scene.request)
    assert r.units_pledged == 3 and r.units_confirmed == 0
    assert r.status == STATUS_APPROVED          # nothing verified, nothing fulfilled
    assert r.progress_percent == 0


def test_fulfilment_cancels_leftover_offers(scene):
    extra = make_donor("O+")
    leftover = offer(extra, scene.request)
    for d in scene.donors:
        allocation.confirm_donation(scene.hospital, offer(d, scene.request).id)
    db.session.expire_all()
    assert db.session.get(DonationResponse, leftover.id).response_status == RESP_CANCELLED


def test_donation_history_and_verifier_recorded(scene):
    resp = offer(scene.donors[0], scene.request)
    allocation.confirm_donation(scene.hospital, resp.id)
    db.session.expire_all()
    resp = db.session.get(DonationResponse, resp.id)
    assert resp.verified_by_hospital_id == scene.hospital.id and resp.verified_at
    assert resp.donor.last_donation_date == date.today()
    assert resp.donor.is_eligible is False          # rest period has started


# ----------------------------------------------------------------------
# Donor edge cases
# ----------------------------------------------------------------------
def test_donor_cancels_after_interest(scene):
    resp = offer(scene.donors[0], scene.request)
    allocation.cancel_response(resp.id, "donor", scene.donors[0].id)
    r = refresh(scene.request)
    assert r.units_pledged == 0 and r.units_confirmed == 0 and r.status == STATUS_APPROVED


def test_cancelled_donor_can_offer_again_on_same_row(scene):
    d = scene.donors[0]
    first = offer(d, scene.request)
    allocation.cancel_response(first.id, "donor", d.id)
    second = offer(d, scene.request)
    assert second.id == first.id and second.response_status == RESP_INTERESTED


def test_ineligible_donor_is_excluded_and_deferred(scene):
    d = scene.donors[0]
    resp = offer(d, scene.request)
    allocation.mark_ineligible(scene.hospital, resp.id, "screening", deferral_days=30)
    db.session.expire_all()
    assert db.session.get(DonationResponse, resp.id).response_status == RESP_INELIGIBLE
    with pytest.raises(AllocationError):           # cannot confirm an ineligible donor
        allocation.confirm_donation(scene.hospital, resp.id)
    other = make_request(scene.patient, scene.hospital, units=1)
    with pytest.raises(AllocationError):           # deferral blocks new offers
        offer(db.session.get(type(d), d.id), other)


def test_duplicate_response_is_rejected(scene):
    offer(scene.donors[0], scene.request)
    with pytest.raises(AllocationError, match="already responded"):
        offer(scene.donors[0], scene.request)
    assert DonationResponse.query.filter_by(request_id=scene.request.id).count() == 1


def test_offer_requires_explicit_consent(scene):
    with pytest.raises(AllocationError, match="agree to share"):
        allocation.pledge(scene.donors[0], scene.request.id, 1, consent_to_share=False)


def test_incompatible_or_unavailable_donor_cannot_offer(scene):
    with pytest.raises(AllocationError, match="not compatible"):
        offer(make_donor("A+"), scene.request)
    with pytest.raises(AllocationError, match="Available"):
        offer(make_donor("O+", availability="Not Available"), scene.request)


def test_donor_cannot_pledge_more_than_remaining(app, scene):
    app.config["MAX_UNITS_PER_DONOR_DONATION"] = 5
    req = make_request(scene.patient, scene.hospital, units=2)
    with pytest.raises(AllocationError, match="Only 2"):
        allocation.pledge(scene.donors[0], req.id, 3, consent_to_share=True)


def test_donor_cannot_cancel_someone_elses_offer(scene):
    resp = offer(scene.donors[0], scene.request)
    with pytest.raises(NotAuthorized):
        allocation.cancel_response(resp.id, "donor", scene.donors[1].id)


# ----------------------------------------------------------------------
# Confirmation rules
# ----------------------------------------------------------------------
def test_same_donation_cannot_be_confirmed_twice(scene):
    resp = offer(scene.donors[0], scene.request)
    allocation.confirm_donation(scene.hospital, resp.id)
    with pytest.raises(AllocationError, match="already been confirmed"):
        allocation.confirm_donation(scene.hospital, resp.id)
    assert refresh(scene.request).units_confirmed == 1


def test_excess_contribution_is_rejected(app, scene):
    app.config["MAX_UNITS_PER_DONOR_DONATION"] = 5
    req = make_request(scene.patient, scene.hospital, units=2)
    resp = allocation.pledge(scene.donors[0], req.id, 1, consent_to_share=True)
    with pytest.raises(AllocationError, match="exceed"):
        allocation.confirm_donation(scene.hospital, resp.id, units=3)
    with pytest.raises(AllocationError):
        allocation.confirm_donation(scene.hospital, resp.id, units=0)
    assert refresh(req).units_confirmed == 0


def test_default_is_one_unit_per_donor(scene):
    resp = offer(scene.donors[0], scene.request)
    with pytest.raises(AllocationError, match="between 1 and 1"):
        allocation.confirm_donation(scene.hospital, resp.id, units=2)


def test_other_hospital_cannot_confirm(scene):
    resp = offer(scene.donors[0], scene.request)
    with pytest.raises(NotAuthorized):
        allocation.confirm_donation(make_hospital(), resp.id)
    assert refresh(scene.request).units_confirmed == 0


def test_cannot_confirm_when_request_is_full(scene):
    for d in scene.donors:
        allocation.confirm_donation(scene.hospital, offer(d, scene.request).id)
    late = DonationResponse(donor_id=make_donor("O+").id, request_id=scene.request.id)
    db.session.add(late)
    db.session.commit()
    with pytest.raises(AllocationError):
        allocation.confirm_donation(scene.hospital, late.id)
    assert refresh(scene.request).units_confirmed == 3


def test_failed_confirmation_rolls_back(scene, monkeypatch):
    resp = offer(scene.donors[0], scene.request)

    def boom(*a, **k):
        raise RuntimeError("notification service down")
    monkeypatch.setattr(allocation, "notify_account", boom)
    with pytest.raises(RuntimeError):
        allocation.confirm_donation(scene.hospital, resp.id)
    db.session.expire_all()
    fresh = db.session.get(DonationResponse, resp.id)
    assert fresh.response_status == RESP_INTERESTED and fresh.units_collected == 0
    assert fresh.donor.last_donation_date is None


# ----------------------------------------------------------------------
# Cancellation and expiry with outstanding offers
# ----------------------------------------------------------------------
def test_request_cancelled_with_outstanding_responses(scene):
    resp = offer(scene.donors[0], scene.request)
    done = offer(scene.donors[1], scene.request)
    allocation.confirm_donation(scene.hospital, done.id)
    allocation.close_request(scene.request.id, "patient", scene.patient.id, "no longer needed")
    r = refresh(scene.request)
    assert r.status == STATUS_CANCELLED and r.closed_reason == "no longer needed"
    assert db.session.get(DonationResponse, resp.id).response_status == RESP_CANCELLED
    assert db.session.get(DonationResponse, done.id).response_status == RESP_COMPLETED  # history kept
    assert Notification.query.filter_by(donor_id=scene.donors[0].id).count() >= 1
    with pytest.raises(AllocationError):
        offer(scene.donors[2], r)                      # closed requests accept nothing


def test_only_owner_can_cancel_and_hospital_needs_reason(scene):
    with pytest.raises(NotAuthorized):
        allocation.close_request(scene.request.id, "patient", make_patient().id)
    with pytest.raises(NotAuthorized):
        allocation.close_request(scene.request.id, "hospital", make_hospital().id, "x")
    with pytest.raises(AllocationError, match="reason"):
        allocation.close_request(scene.request.id, "hospital", scene.hospital.id, "")


def test_request_expires_before_all_units_collected(scene):
    done = offer(scene.donors[0], scene.request)
    allocation.confirm_donation(scene.hospital, done.id)
    waiting = offer(scene.donors[1], scene.request)
    r = refresh(scene.request)
    r.expiry_date = datetime.utcnow() - timedelta(hours=1)
    db.session.commit()
    assert expire_old_requests(force=True) == 1
    r = refresh(scene.request)
    assert r.status == STATUS_EXPIRED and r.units_confirmed == 1
    assert db.session.get(DonationResponse, waiting.id).response_status == RESP_CANCELLED
    assert expire_old_requests(force=True) == 0        # idempotent


# ----------------------------------------------------------------------
# Concurrency
# ----------------------------------------------------------------------
def test_two_hospital_users_confirming_the_final_unit_simultaneously(app, scene):
    """Only ONE of two simultaneous confirmations may take the last unit."""
    allocation.confirm_donation(scene.hospital, offer(scene.donors[0], scene.request).id)
    allocation.confirm_donation(scene.hospital, offer(scene.donors[1], scene.request).id)
    contenders = [make_donor("O+"), make_donor("O+")]
    ids = [offer(d, scene.request).id for d in contenders]
    hospital_id, results = scene.hospital.id, []
    barrier = threading.Barrier(2)

    def worker(resp_id):
        with app.app_context():
            from models import Hospital
            hospital = db.session.get(Hospital, hospital_id)
            barrier.wait()
            try:
                allocation.confirm_donation(hospital, resp_id)
                results.append("ok")
            except AllocationError:
                results.append("rejected")
            finally:
                db.session.remove()

    threads = [threading.Thread(target=worker, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "rejected"]
    r = refresh(scene.request)
    assert r.units_confirmed == 3 and r.units_remaining == 0 and r.status == STATUS_FULFILLED
    assert allocation.check_consistency() == []


# ----------------------------------------------------------------------
# Formulas and consistency
# ----------------------------------------------------------------------
@pytest.mark.parametrize("required,confirmed,remaining,percent", [
    (3, 0, 3, 0), (3, 1, 2, 33.33), (3, 3, 0, 100), (3, 5, 0, 100), (0, 0, 0, 0), (-2, 1, 0, 0), (None, 0, 0, 0)])
def test_formulas_handle_invalid_values(required, confirmed, remaining, percent):
    req = int(required or 0)
    assert allocation.remaining_formula(req, confirmed) == remaining
    assert round(allocation.percent_formula(req, confirmed), 2) == percent


def test_invalid_required_units_do_not_crash_progress(scene):
    r = scene.request
    r.units_required = None
    assert (r.required, r.units_remaining, r.progress_percent) == (0, 0, 0)


def test_consistency_check_detects_tampering(scene):
    resp = offer(scene.donors[0], scene.request)
    allocation.confirm_donation(scene.hospital, resp.id)
    assert allocation.check_consistency() == []
    scene.request.status = STATUS_FULFILLED          # forged: only 1 of 3 confirmed
    db.session.commit()
    assert any("Fulfilled but only 1/3" in p for p in allocation.check_consistency())
