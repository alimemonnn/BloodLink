"""Create the database and fill it with realistic demo data.

Run once before the first demo:

    python seed.py

Default admin login:  admin@bloodlink.com / Admin123
"""
from datetime import date, datetime, timedelta

from app import create_app
from models import (STATUS_APPROVED, STATUS_FULFILLED, STATUS_PENDING,
                    Admin, BloodRequest, DonationResponse, Donor, Hospital,
                    Notification, Patient, db)
from utils.notifications import notify_matching_donors

app = create_app()


def days_ago(n):
    return date.today() - timedelta(days=n)


def seed():
    db.drop_all()
    db.create_all()

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
        p = Patient(name=name, email=email, phone=phone, city=city, address=address)
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
                         response_status="Donation Completed", donation_date=days_ago(40)),
    ])
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
    import sys

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    # seed() DROPS every table first. Against a real (cloud) database that
    # would erase live data, so it must be requested explicitly.
    if not uri.startswith("sqlite") and "--force" not in sys.argv:
        print("Refusing to run: this would ERASE the database at DATABASE_URL.")
        print("If you really want demo data on it, run:  python seed.py --force")
        sys.exit(1)
    with app.app_context():
        seed()
