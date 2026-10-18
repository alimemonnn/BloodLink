"""Fill an EMPTY database with fake demo data (development / demo only).

    python seed.py            # only works on an empty database
    python seed.py --reset    # ERASES every table first (asks you to type YES)

Never run this against a real deployment: it refuses when ENVIRONMENT/FLASK_ENV
is production. All people below are fictional and use example.com addresses.
Demo logins are printed at the end and exist only in your local database.
"""
import sys
from datetime import date, datetime, timedelta

from app import create_app
from config import IS_PRODUCTION
from models import (BloodStock, Camp, RESP_COMPLETED, RESP_SCHEDULED, STATUS_APPROVED, STATUS_FULFILLED,
                    STATUS_PARTIAL, STATUS_PENDING, Admin, BloodRequest,
                    ChatMessage, ConsentRecord, DonationResponse, Donor, Hospital,
                    Notification, Patient, db)
from utils.notifications import notify_matching_donors

app = create_app()


def days_ago(n):
    return date.today() - timedelta(days=n)


def seed(reset=False):
    if IS_PRODUCTION:
        raise SystemExit("Refusing to seed a production environment.")
    if reset:
        if input("This ERASES all data in the configured database. Type YES to continue: ") != "YES":
            raise SystemExit("Cancelled. Nothing was changed.")
        db.drop_all()
    db.create_all()
    if Donor.query.first() or Admin.query.first():
        raise SystemExit("The database already has data. Nothing was changed. "
                         "Use `python seed.py --reset` only if you really want to wipe it.")

    # ------------------------------------------------------------------
    # Admin (password is hashed, never stored as plain text)
    # ------------------------------------------------------------------
    admin = Admin(name="System Administrator", email="admin@bloodlink.com")
    admin.set_password("Admin123")
    db.session.add(admin)

    # ------------------------------------------------------------------
    # Hospitals
    # ------------------------------------------------------------------
    hospital_data = [
        ("Sukkur Civil Hospital", "civil@sukkurhospital.com", "0713540011",
         "Shikarpur Road", "Sukkur", True),
        ("Ghulam Muhammad Mahar Medical College Hospital", "info@gmmmc.edu.pk", "0713510022",
         "Airport Road", "Sukkur", True),
        ("Rohri General Hospital", "contact@rohrigh.com", "0713420033",
         "Station Road", "Rohri", True),
        ("Larkana Blood Centre", "help@larkanablood.com", "0744560044",
         "Jinnah Bagh Road", "Larkana", False),   # waiting for admin verification
    ]
    hospitals = []
    for name, email, phone, address, city, verified in hospital_data:
        h = Hospital(hospital_name=name, email=email, phone=phone,
                     address=address, city=city, is_verified=verified, is_active=True)
        h.set_password("Hospital123")
        hospitals.append(h)
        db.session.add(h)

    # ------------------------------------------------------------------
    # Donors (mix of blood groups, cities and eligibility states)
    # ------------------------------------------------------------------
    donor_data = [
        ("Ahmed Ali", "ahmed.ali@example.com", "03001234501", "B+", "Sukkur", "Minara Road", days_ago(200), "Available"),
        ("Muhammad Hassan", "m.hassan@example.com", "03001234502", "O+", "Sukkur", "Military Road", days_ago(150), "Available"),
        ("Ali Raza", "ali.raza@example.com", "03001234503", "B-", "Rohri", "Station Road", None, "Available"),
        ("Bilal Ahmed", "bilal@example.com", "03001234504", "O-", "Sukkur", "Barrage Colony", days_ago(120), "Available"),
        ("Sana Khan", "sana.khan@example.com", "03001234505", "A+", "Sukkur", "Queens Road", days_ago(30), "Available"),
        ("Fatima Sheikh", "fatima@example.com", "03001234506", "AB+", "Larkana", "Bakrani Road", None, "Available"),
        ("Usman Memon", "usman@example.com", "03001234507", "B+", "Rohri", "Ghanta Ghar", days_ago(400), "Not Available"),
        ("Hira Soomro", "hira@example.com", "03001234508", "A-", "Sukkur", "New Pind", days_ago(95), "Available"),
        ("Kashif Abro", "kashif@example.com", "03001234509", "O+", "Larkana", "VIP Road", None, "Available"),
        ("Zainab Qureshi", "zainab@example.com", "03001234510", "AB-", "Sukkur", "Shalimar", days_ago(240), "Available"),
        ("Imran Shah", "imran@example.com", "03001234511", "B+", "Khairpur", "Kotwali", days_ago(20), "Available"),
        ("Nadia Baloch", "nadia@example.com", "03001234512", "O-", "Rohri", "Civil Lines", None, "Available"),
    ]
    donors = []
    for name, email, phone, group, city, area, last, availability in donor_data:
        d = Donor(name=name, email=email, phone=phone, blood_group=group, city=city,
                  area=area, last_donation_date=last, availability=availability, is_active=True)
        d.set_password("Donor123")
        d.refresh_eligibility()
        d.share_contact_consent = group in ("B+", "O+", "O-")   # demo: a mix of consent choices
        d.terms_accepted_at = d.age_confirmed_at = d.health_data_consent_at = datetime.utcnow()
        d.policy_version = app.config["POLICY_VERSION"]
        donors.append(d)
        db.session.add(d)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    patient_data = [
        ("Rizwan Sheikh", "rizwan@example.com", "03111234501", "Sukkur", "House 24, Minara Road"),
        ("Ayesha Siddiqui", "ayesha@example.com", "03111234502", "Rohri", "House 8, Station Road"),
        ("Farhan Chandio", "farhan@example.com", "03111234503", "Larkana", "House 51, VIP Road"),
    ]
    patients = []
    for name, email, phone, city, address in patient_data:
        p = Patient(name=name, email=email, phone=phone, city=city,
                    terms_accepted_at=datetime.utcnow(), age_confirmed_at=datetime.utcnow(),
                    policy_version=app.config["POLICY_VERSION"])
        p.set_password("Patient123")
        patients.append(p)
        db.session.add(p)

    db.session.commit()

    # ------------------------------------------------------------------
    # Blood requests, at every stage of the workflow
    # ------------------------------------------------------------------
    requests = [
        BloodRequest(patient_id=patients[0].id, hospital_id=hospitals[0].id,
                     patient_name="Rizwan Sheikh", blood_group_required="B+",
                     units_required=2, urgency="Critical", location="Sukkur",
                     contact_number="03111234501",
                     description="Surgery scheduled for tomorrow morning, ward 3.",
                     status=STATUS_APPROVED, hospital_verified=True,
                     hospital_notes="Patient admitted, requirement confirmed by the blood bank."),
        BloodRequest(patient_id=patients[1].id, hospital_id=hospitals[2].id,
                     patient_name="Ayesha Siddiqui's mother", blood_group_required="A+",
                     units_required=1, urgency="Urgent", location="Rohri",
                     contact_number="03111234502",
                     description="Anaemia treatment, transfusion needed within two days.",
                     status=STATUS_PENDING),
        BloodRequest(patient_id=patients[2].id, hospital_id=hospitals[1].id,
                     patient_name="Farhan Chandio", blood_group_required="O-",
                     units_required=3, urgency="Critical", location="Sukkur",
                     contact_number="03111234503",
                     description="Road accident, emergency department.",
                     status=STATUS_APPROVED, hospital_verified=True),
        BloodRequest(patient_id=patients[0].id, hospital_id=hospitals[0].id,
                     patient_name="Rizwan Sheikh's uncle", blood_group_required="AB+",
                     units_required=1, urgency="Normal", location="Sukkur",
                     contact_number="03111234501",
                     description="Planned procedure next month.",
                     status=STATUS_FULFILLED, hospital_verified=True),
    ]
    # Multi-donor demo: 3 units of O+ needed, 2 already verified by the hospital.
    multi = BloodRequest(patient_id=patients[1].id, hospital_id=hospitals[0].id,
                         patient_name="Demo Patient", blood_group_required="O+",
                         units_required=3, urgency="Urgent", location="Sukkur",
                         contact_number="03111234502",
                         description="Demo of a three-unit request.",
                         status=STATUS_PARTIAL, hospital_verified=True)
    requests.append(multi)
    db.session.add_all(requests)
    db.session.commit()

    # ------------------------------------------------------------------
    # Donor responses
    # ------------------------------------------------------------------
    db.session.add_all([
        DonationResponse(donor_id=donors[0].id, request_id=requests[0].id,
                         response_status="Contacted"),
        DonationResponse(donor_id=donors[1].id, request_id=requests[0].id,
                         response_status="Interested"),
        DonationResponse(donor_id=donors[3].id, request_id=requests[3].id,
                         response_status=RESP_COMPLETED, units_collected=1,
                         donation_date=days_ago(40), verified_by_hospital_id=hospitals[0].id,
                         verified_at=datetime.utcnow() - timedelta(days=40)),
        # Three-unit request: two verified donations, one donor still interested
        DonationResponse(donor_id=donors[8].id, request_id=multi.id, response_status=RESP_COMPLETED,
                         units_collected=1, donation_date=days_ago(1),
                         verified_by_hospital_id=hospitals[0].id, verified_at=datetime.utcnow()),
        DonationResponse(donor_id=donors[1].id, request_id=multi.id, response_status=RESP_COMPLETED,
                         units_collected=1, donation_date=days_ago(1),
                         verified_by_hospital_id=hospitals[0].id, verified_at=datetime.utcnow()),
        DonationResponse(donor_id=donors[3].id, request_id=multi.id, response_status=RESP_SCHEDULED,
                         contact_consent_at=datetime.utcnow(),
                         appointment_at=(datetime.utcnow() + timedelta(days=1)).replace(hour=17, minute=30, second=0, microsecond=0)),
    ])
    # A short demo conversation on each of two live offers
    def conversation(donor, req, lines):
        resp = DonationResponse.query.filter_by(donor_id=donor.id, request_id=req.id).first()
        who = {"d": ("donor", donor.id), "p": ("patient", req.patient_id), "h": ("hospital", req.hospital_id),
               "e": ("system", 0)}
        t = datetime.utcnow() - timedelta(minutes=5 * len(lines))
        for i, (sender, text) in enumerate(lines):
            role, uid = who[sender]
            db.session.add(ChatMessage(response_id=resp.id, sender_role=role, sender_id=uid,
                                       body=text, kind="event" if sender == "e" else "text",
                                       created_at=t + timedelta(minutes=5 * i)))
        db.session.commit()

    conversation(donors[3], multi, [
        ("e", "The donor offered 1 unit(s). Use this chat to agree a time with the hospital."),
        ("d", "Hello, I saw the request and I am free this evening. Which ward should I come to?"),
        ("p", "Thank you so much. The blood bank at the hospital, ground floor. Ask for the O+ request."),
        ("h", "Hello. Please come between 5 and 7 pm and bring your CNIC. We will screen you before collecting."),
        ("e", "Appointment scheduled for tomorrow at 17:30."),
        ("d", "Understood, I will be there at 5:30."),
    ])
    conversation(donors[0], requests[0], [
        ("h", "Thanks for offering. Are you available tomorrow morning for a short screening?"),
        ("d", "Yes, around 10 am works for me."),
    ])

    # Self-reported blood stock and an upcoming donation camp
    for hospital, units in ((hospitals[0], {"O+": 9, "A+": 5, "B+": 4, "AB+": 2, "O-": 1, "A-": 3, "B-": 0, "AB-": 1}),
                            (hospitals[1], {"O+": 3, "A+": 2, "B+": 6, "O-": 0})):
        for group, n in units.items():
            db.session.add(BloodStock(hospital_id=hospital.id, blood_group=group, units=n))
    db.session.add(Camp(hospital_id=hospitals[0].id, title="World Blood Donor Day camp", venue="Civil Hospital lawn",
                        city=hospitals[0].city, starts_at=datetime.utcnow() + timedelta(days=5, hours=2),
                        ends_at=datetime.utcnow() + timedelta(days=5, hours=8), capacity=60,
                        description="Free screening for everyone. Bring a photo ID."))
    db.session.commit()

    donors[1].last_donation_date = donors[8].last_donation_date = days_ago(1)
    for d in donors:
        d.refresh_eligibility()
        db.session.add(ConsentRecord(subject_role="donor", subject_id=d.id, purpose="terms_privacy",
                                     policy_version=app.config["POLICY_VERSION"]))
    db.session.commit()

    # Notifications for the two approved requests
    for req in (requests[0], requests[2]):
        notify_matching_donors(req)

    print("Database seeded.")
    print("-" * 52)
    print("Admin     : admin@bloodlink.com / Admin123")
    print("Hospital  : civil@sukkurhospital.com / Hospital123")
    print("Donor     : ahmed.ali@example.com / Donor123")
    print("Patient   : rizwan@example.com / Patient123")
    print("-" * 52)
    print(f"{len(donors)} donors, {len(patients)} patients, "
          f"{len(hospitals)} hospitals, {len(requests)} blood requests.")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    with app.app_context():
        seed(reset=reset_flag)
