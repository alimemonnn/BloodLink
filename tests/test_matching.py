"""Blood-group compatibility (red cells) and donor matching."""
from datetime import date, timedelta

import pytest

from conftest import make_donor, make_hospital, make_patient, make_request
from models import db
from utils import allocation
from utils.matching import (BLOOD_GROUPS, CAN_DONATE_TO, can_donate,
                            compatible_donor_groups, find_matching_donors, rank_donors)

# Standard ABO/Rh red-cell compatibility: recipient -> allowed donor groups
EXPECTED = {
    "O-": {"O-"}, "O+": {"O-", "O+"},
    "A-": {"O-", "A-"}, "A+": {"O-", "O+", "A-", "A+"},
    "B-": {"O-", "B-"}, "B+": {"O-", "O+", "B-", "B+"},
    "AB-": {"O-", "A-", "B-", "AB-"}, "AB+": set(BLOOD_GROUPS),
}


@pytest.mark.parametrize("recipient", BLOOD_GROUPS)
def test_compatibility_table(recipient):
    assert set(compatible_donor_groups(recipient)) == EXPECTED[recipient]


def test_specific_rules_from_the_brief():
    assert can_donate("O-", "AB+") and can_donate("O-", "O-")
    assert not can_donate("A+", "B+") and not can_donate("A+", "O+")
    assert not can_donate("O+", "O-")                 # Rh+ never gives to Rh-
    assert not can_donate("AB+", "A+")
    assert not can_donate("XX", "A+") and not can_donate(None, "A+")


def test_each_donor_group_maps_to_recipients_consistently():
    for donor, recipients in CAN_DONATE_TO.items():
        for r in recipients:
            assert donor in EXPECTED[r]


@pytest.fixture
def ctx(app):
    return type("C", (), dict(h=make_hospital(), p=make_patient()))


def test_incompatible_groups_are_filtered(ctx):
    req = make_request(ctx.p, ctx.h, group="B+", units=1)
    ok = [make_donor("B+"), make_donor("O-")]
    make_donor("A+"), make_donor("AB+")
    assert {d.id for d in find_matching_donors(req)} == {d.id for d in ok}


def test_unavailable_inactive_and_recent_donors_are_filtered(ctx):
    req = make_request(ctx.p, ctx.h, group="O+", units=1)
    good = make_donor("O+")
    make_donor("O+", availability="Not Available")
    inactive = make_donor("O+"); inactive.is_active = False
    make_donor("O+", last=date.today() - timedelta(days=10))      # rest period
    db.session.commit()
    assert [d.id for d in find_matching_donors(req)] == [good.id]


def test_deferred_donor_is_filtered_until_date(ctx):
    req = make_request(ctx.p, ctx.h, group="O+", units=1)
    d = make_donor("O+")
    d.deferred_until = date.today() + timedelta(days=5)
    db.session.commit()
    assert find_matching_donors(req) == []
    d.deferred_until = date.today() - timedelta(days=1)
    db.session.commit()
    assert find_matching_donors(req) == [d]


def test_donors_who_already_responded_are_not_listed_again(ctx):
    req = make_request(ctx.p, ctx.h, group="O+", units=3)
    d1, d2 = make_donor("O+"), make_donor("O+")
    allocation.pledge(d1, req.id, 1, consent_to_share=True)
    assert [d.id for d in find_matching_donors(req)] == [d2.id]


def test_same_city_and_exact_group_rank_first_and_explain_why(ctx):
    req = make_request(ctx.p, ctx.h, group="O+", units=1, location="Sukkur")
    far_exact = make_donor("O+", city="Karachi")
    near_neg = make_donor("O-", city="Sukkur")
    near_exact = make_donor("O+", city="Sukkur")
    ranked = rank_donors(req)
    assert [m.donor.id for m in ranked] == [near_exact.id, near_neg.id, far_exact.id]
    assert ranked[0].score > ranked[1].score > ranked[2].score
    assert "Same city as the hospital" in ranked[0].reasons
    assert "Exact blood group" in ranked[0].reasons


def test_score_never_overrides_hard_filters(ctx):
    req = make_request(ctx.p, ctx.h, group="O+", units=1)
    make_donor("O+", availability="Not Available", city="Sukkur")        # perfect score, but unavailable
    assert rank_donors(req) == []


def test_empty_results_and_missing_donor_data(ctx):
    req = make_request(ctx.p, ctx.h, group="AB-", units=1)
    assert find_matching_donors(req) == []
    d = make_donor("O-", city="")                    # no city on file: falls back safely
    assert [m.donor.id for m in rank_donors(req)] == [d.id]


def test_limit_and_unknown_group(ctx):
    req = make_request(ctx.p, ctx.h, group="O+", units=1)
    for _ in range(4):
        make_donor("O+")
    assert len(find_matching_donors(req, limit=2)) == 2
    assert compatible_donor_groups("ZZ") == []
