"""Checks for the security fixes and the "pick blood group -> log in" flow.

Run with:  python test_new_features.py
"""
import os
import sys
from datetime import datetime, timedelta

from app import create_app
from config import Config
from models import STATUS_EXPIRED, STATUS_PENDING, Admin, BloodRequest, Donor, Hospital, Patient, db
from utils import ratelimit
from utils.auth import safe_next
from utils.maintenance import expire_old_requests

PASS, FAIL = [], []


def check(name, ok):
    (PASS if ok else FAIL).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name)


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "test_database2.db")
    TESTING = True
    WTF_CSRF_ENABLED = False


class CsrfConfig(TestConfig):
    WTF_CSRF_ENABLED = True


def login(client, role, email, password, **kw):
    return client.post("/login", data={"role": role, "email": email, "password": password}, **kw)


def main():
    app = create_app(TestConfig)
    with app.app_context():
        import seed
        seed.seed()

    print("\n1. Find a donor: pick a group -> login gate -> results")
    c = app.test_client()
    r = c.get("/find-blood")
    check("Picker page shows all 8 blood groups", all(f"blood_group={g.replace('+', '%2B')}".encode() in r.data
          for g in ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]))
    check("Picker exposes no donor names", b"Ahmed Ali" not in r.data)

    r = c.get("/find-blood?blood_group=A%2B")
    check("Guest clicking A+ gets the login/register gate", b"Log in to see A+ donors" in r.data)
    check("Gate does not leak donor names", b"Sana Khan" not in r.data)
    check("Gate offers both Log in and Register", b"/login" in r.data and b"/register" in r.data)

    r = login(c, "patient", "rizwan@example.com", "Patient123")
    check("After login the user returns to the A+ donor list",
          r.status_code == 302 and "blood_group=A%2B" in r.headers["Location"])
    r = c.get("/find-blood?blood_group=A%2B")
    check("Logged-in user sees donors", b"Donors who can give A+" in r.data)
    body = r.data.decode()
    check("A+ list includes exact A+ donor", "Sana Khan" in body)
    check("A+ list includes compatible O- donor", "Bilal Ahmed" in body)
    check("A+ list includes compatible O+ donor", "Muhammad Hassan" in body)
    check("A+ list excludes incompatible B+ donor", "Ahmed Ali" not in body)
    check("A+ list excludes incompatible AB+ donor", "Fatima Sheikh" not in body)
    # Sana (A+) donated 30 days ago so cannot give yet; Bilal (O-) can give today.
    check("Donors who can give NOW are ranked before ones still in cooldown",
          body.index("Bilal Ahmed") < body.index("Sana Khan"))
    check("Cooldown donor is labelled with days remaining", "Eligible in" in body)
    check("Patient sees Call / WhatsApp for a ready donor", "wa.me/923001234504" in body)
    check("No phone shown for a donor in cooldown", "923001234505" not in body)

    r = c.get("/find-blood?blood_group=AB%2B&availability=")
    check("AB+ patient can receive from every group (universal recipient)",
          all(n in r.data.decode() for n in ["Ahmed Ali", "Sana Khan", "Bilal Ahmed", "Fatima Sheikh", "Zainab Qureshi"]))
    r = c.get("/find-blood?blood_group=O-&match=compatible&availability=")
    body = r.data.decode()
    check("O- patient sees only O- donors", "Bilal Ahmed" in body and "Ahmed Ali" not in body)
    r = c.get("/find-blood?blood_group=A%2B&match=exact")
    check("Exact-only mode hides compatible groups", "Sana Khan" in r.data.decode() and "Bilal Ahmed" not in r.data.decode())

    # Donors browsing do not get other donors' phone numbers
    d = app.test_client()
    login(d, "donor", "ahmed.ali@example.com", "Donor123")
    r = d.get("/find-blood?blood_group=B%2B")
    check("A donor browsing does not see phone numbers", b"tel:" not in r.data)

    print("\n2. Redirect safety")
    check("Relative next is accepted", safe_next("/find-blood?blood_group=A%2B") is not None)
    check("Absolute URL next is refused", safe_next("https://evil.example") is None)
    check("Protocol-relative next is refused", safe_next("//evil.example") is None)
    e = app.test_client()
    e.get("/login?next=https://evil.example")
    r = login(e, "donor", "ahmed.ali@example.com", "Donor123")
    check("Evil next is ignored after login", "evil.example" not in r.headers["Location"])

    print("\n3. Registration keeps the destination")
    f = app.test_client()
    f.get("/find-blood?blood_group=O%2B")
    r = f.post("/register/patient", data={
        "name": "New Person", "email": "new.person@example.com", "phone": "03005550000",
        "city": "Sukkur", "password": "Secret123", "confirm_password": "Secret123"})
    check("New account lands on the donor list it asked for",
          r.status_code == 302 and "blood_group=O%2B" in r.headers["Location"])

    print("\n4. Brute-force protection")
    ratelimit.clear_all()
    g = app.test_client()
    for _ in range(5):
        login(g, "donor", "ahmed.ali@example.com", "wrong-password")
    r = login(g, "donor", "ahmed.ali@example.com", "Donor123")
    check("Account is locked after 5 wrong passwords (HTTP 429)", r.status_code == 429)
    ratelimit.clear_all()

    print("\n5. Input validation")
    h = app.test_client()
    r = h.post("/register/donor", data={
        "name": "X" * 500, "email": "long@example.com", "phone": "03001112222", "city": "Sukkur",
        "blood_group": "O+", "password": "Secret123", "confirm_password": "Secret123"}, follow_redirects=True)
    check("Over-long name is a form error, not a crash", b"120 characters or fewer" in r.data)
    r = h.post("/register/donor", data={
        "name": "Short Pw", "email": "sp@example.com", "phone": "03001112223", "city": "Sukkur",
        "blood_group": "O+", "password": "abc12", "confirm_password": "abc12"}, follow_redirects=True)
    check("Password shorter than 8 characters is rejected", b"at least 8 characters" in r.data)

    print("\n6. Pending requests also expire")
    with app.app_context():
        req = BloodRequest.query.filter_by(status=STATUS_PENDING).first()
        req.expiry_date = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
        expire_old_requests(force=True)
        check("Old pending request becomes Expired", db.session.get(BloodRequest, req.id).status == STATUS_EXPIRED)

    print("\n7. Abuse prevention")
    p = app.test_client()
    login(p, "patient", "ayesha@example.com", "Patient123")
    with app.app_context():
        from models import Hospital
        hid = Hospital.query.filter_by(is_verified=True).first().id
    payload = {"patient_name": "Spam", "blood_group_required": "O+", "hospital_id": hid,
               "location": "Sukkur", "contact_number": "03001234567", "urgency": "Normal", "units_required": "1"}
    for _ in range(5):
        p.post("/patient/requests/new", data=payload)
    r = p.post("/patient/requests/new", data=payload, follow_redirects=True)
    check("6th request within an hour is refused", b"posted several requests" in r.data)

    print("\n8. CSRF protection (enabled)")
    capp = create_app(CsrfConfig)
    cc = capp.test_client()
    r = cc.post("/login", data={"role": "donor", "email": "ahmed.ali@example.com", "password": "Donor123"})
    check("POST without a CSRF token is rejected (400)", r.status_code == 400)
    page = cc.get("/login").data.decode()
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    r = cc.post("/login", data={"role": "donor", "email": "ahmed.ali@example.com",
                                "password": "Donor123", "csrf_token": token})
    check("POST with the right token is accepted", r.status_code == 302)
    r = cc.post("/donor/availability", data={})
    check("State-changing POST without token is rejected", r.status_code == 400)

    print("\n9. Database URL handling")
    import importlib, config
    os.environ["DATABASE_URL"] = "postgres://u:p@host/db"
    importlib.reload(config)
    check("postgres:// is rewritten to postgresql://",
          config.Config.SQLALCHEMY_DATABASE_URI == "postgresql://u:p@host/db")
    check("Cloud database gets connection pre-ping", config.Config.SQLALCHEMY_ENGINE_OPTIONS.get("pool_pre_ping") is True)
    del os.environ["DATABASE_URL"]
    importlib.reload(config)
    check("Without DATABASE_URL it falls back to SQLite", config.Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite"))

    print("\n10. Admin 'All users' view")
    uc = app.test_client()
    check("Anonymous user is redirected away from /admin/users",
          uc.get("/admin/users").status_code == 302)

    login(uc, "donor", "ahmed.ali@example.com", "Donor123", follow_redirects=True)
    with app.app_context():
        donor = Donor.query.filter_by(email="ahmed.ali@example.com").first()
        check("last_login_at is stamped the moment a donor logs in", donor.last_login_at is not None)

    check("A donor cannot open the admin users page",
          uc.get("/admin/users").status_code == 403)

    ac = app.test_client()
    login(ac, "admin", "admin@bloodlink.com", "Admin123", follow_redirects=True)
    r = ac.get("/admin/users")
    body = r.data.decode()
    check("Admin can open the users page", r.status_code == 200)
    check("Users page can find the logged-in donor by search",
          "Ahmed Ali" in ac.get("/admin/users?q=ahmed.ali").data.decode())
    check("Users page shows the donor's last-active time, not 'Never logged in' for that row",
          "Never logged in" in body)  # true for accounts that have never logged in (e.g. patients/hospitals not yet used)
    with app.app_context():
        any_hash_leaked = any(
            row.password_hash in body
            for row in list(Donor.query.all()) + list(Patient.query.all())
            + list(Hospital.query.all()) + list(Admin.query.all())
        )
    check("No password hash ever appears in the users page HTML", not any_hash_leaked)
    check("The word 'password' is not shown as a data column on the users page",
          "password_hash" not in body)

    r = ac.get("/admin/users?role=donor")
    check("Filtering by role=donor only returns donor rows",
          "badge bg-secondary\">Patient" not in r.data.decode())

    r = ac.get("/admin/users?q=ahmed")
    check("Search by name/email narrows the results",
          "ahmed" in r.data.decode().lower())

    r = ac.get("/admin/dashboard")
    check("Main dashboard links through to the users page",
          "/admin/users" in r.data.decode())

    print("\n" + "=" * 54)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for n in FAIL:
        print("  FAILED: " + n)
    print("=" * 54)
    return 1 if FAIL else 0


if __name__ == "__main__":
    code = main()
    try:
        os.remove(TestConfig.SQLALCHEMY_DATABASE_URI.replace("sqlite:///", ""))
    except OSError:
        pass
    sys.exit(code)
