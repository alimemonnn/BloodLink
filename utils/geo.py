"""Distances. No map service is used: city centres are built in, and people may add a rounded area.

Donors who give an optional approximate area (rounded to about 1 km) and hospitals that set an
exact position get precise distances; everyone else falls back to the centre of their city.
"""
import math

# Approximate city centres (latitude, longitude). Names are matched case-insensitively.
CITY_COORDS = {
    "karachi": (24.8607, 67.0011), "lahore": (31.5204, 74.3587), "islamabad": (33.6844, 73.0479),
    "rawalpindi": (33.5651, 73.0169), "faisalabad": (31.4504, 73.1350), "multan": (30.1575, 71.5249),
    "hyderabad": (25.3960, 68.3578), "peshawar": (34.0151, 71.5249), "quetta": (30.1798, 66.9750),
    "sukkur": (27.7052, 68.8574), "larkana": (27.5590, 68.2123), "mirpur khas": (25.5276, 69.0111),
    "mirpurkhas": (25.5276, 69.0111), "nawabshah": (26.2442, 68.4100),
    "shaheed benazirabad": (26.2442, 68.4100), "jacobabad": (28.2769, 68.4514),
    "khairpur": (27.5295, 68.7592), "shikarpur": (27.9556, 68.6382), "ghotki": (28.0059, 69.3142),
    "dadu": (26.7319, 67.7750), "thatta": (24.7461, 67.9244), "badin": (24.6560, 68.8370),
    "sialkot": (32.4945, 74.5229), "gujranwala": (32.1877, 74.1945), "gujrat": (32.5742, 74.0789),
    "bahawalpur": (29.3956, 71.6836), "sargodha": (32.0740, 72.6861), "sahiwal": (30.6682, 73.1114),
    "dera ghazi khan": (30.0561, 70.6340), "rahim yar khan": (28.4202, 70.2952),
    "jhang": (31.2681, 72.3181), "kasur": (31.1187, 74.4500), "abbottabad": (34.1688, 73.2215),
    "mardan": (34.1989, 72.0231),
}


def city_point(city):
    return CITY_COORDS.get((city or "").strip().lower())


def _valid(lat, lng):
    return lat is not None and lng is not None


def haversine_km(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def hospital_point(hospital):
    if hospital is None:
        return None
    if _valid(hospital.lat, hospital.lng):
        return (hospital.lat, hospital.lng)
    return city_point(hospital.city)


def donor_point(donor):
    if _valid(donor.area_lat, donor.area_lng):
        return (donor.area_lat, donor.area_lng)
    return city_point(donor.city)


def distance_km(donor, hospital):
    a, b = donor_point(donor), hospital_point(hospital)
    return None if a is None or b is None else haversine_km(a, b)


def clean_area(lat, lng):
    """Validate and coarsen a donor's area to 2 decimals (about 1 km). Returns (lat, lng) or (None, None)."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return round(lat, 2), round(lng, 2)
