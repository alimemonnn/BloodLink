"""Donors near a hospital, for the hospital's request page ("GPS-style" view).

No map service is used (the site loads nothing from outside). Distances come from ``utils.geo``:
exact for donors who shared an approximate area and for hospitals with a position, otherwise the
centre of the city. The plot is a simple radar: the hospital in the middle, north at the top, rings
every third of the plotted range.

Only donors that matching already allows are listed (compatible group, active, available, rested,
not deferred, not already responded), so this is the same shortlist as the suggested donors, ordered
by distance instead of by score.
"""
import hashlib
import math
from collections import namedtuple

from utils import geo
from utils.cnic import is_verified
from utils.matching import rank_donors

RADIUS_CHOICES = (10, 25, 50, 100)           # km; ``None`` means "any distance"
DEFAULT_RADIUS = 50
_SCALES = (5, 10, 25, 50, 100, 250, 500, 1000)
SIZE, CENTRE, PLOT_R = 400, 200, 165

Near = namedtuple("Near", "donor km precise verified x y")


def _bearing(origin, point):
    """Compass bearing in radians from ``origin`` to ``point`` (0 = north, clockwise)."""
    (lat1, lon1), (lat2, lon2) = origin, point
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.atan2(dx, dy)


def _spread_angle(donor_id):
    """A steady pseudo-angle for donors whose position is only the city centre."""
    h = int(hashlib.sha256(f"near|{donor_id}".encode()).hexdigest()[:8], 16)
    return (h % 3600) / 3600 * 2 * math.pi


def _scale_for(max_km):
    for s in _SCALES:
        if max_km <= s:
            return s
    return _SCALES[-1]


def nearby_donors(blood_request, radius_km=DEFAULT_RADIUS, verified_only=False, origin=None):
    """Return ``(rows, scale_km, hospital_has_position)``; rows are ``Near`` sorted nearest first.

    ``origin`` is an optional ``(lat, lng)`` (the hospital's live GPS reading). Without it the hospital's
    saved position, or its city centre, is used.
    """
    hospital = blood_request.hospital
    if origin is None:
        origin = geo.hospital_point(hospital)
    found = []
    for match in rank_donors(blood_request):
        donor = match.donor
        point = geo.donor_point(donor)
        km = geo.haversine_km(point, origin) if point is not None and origin is not None else None
        if radius_km is not None and (km is None or km > radius_km):
            continue
        verified = is_verified(donor)
        if verified_only and not verified:
            continue
        found.append((donor, km, donor.area_lat is not None and donor.area_lng is not None, verified))
    found.sort(key=lambda r: (r[1] is None, r[1] if r[1] is not None else 0.0, r[0].name.lower()))

    known = [r[1] for r in found if r[1] is not None]
    scale = _scale_for(max(known)) if known else _SCALES[0]
    ring = scale / 3.0
    rows = []
    for donor, km, precise, verified in found:
        x = y = None
        if km is not None and origin is not None:
            if precise and km >= 0.3:
                angle, r_km = _bearing(origin, geo.donor_point(donor)), km
            else:                                      # city-level: draw it on the first ring, spread out
                angle, r_km = _spread_angle(donor.id), max(km, ring * 0.6)
            r = min(r_km / scale, 1.0) * PLOT_R
            x, y = round(CENTRE + r * math.sin(angle), 1), round(CENTRE - r * math.cos(angle), 1)
        rows.append(Near(donor, km, precise, verified, x, y))
    return rows, scale, origin is not None
