"""Real email delivery, tested against a small local SMTP server with TLS and a login.

This is the code path used with Gmail, Brevo, SendGrid and similar providers (port 587 STARTTLS or 465 SSL).
"""
import datetime
import email
import ipaddress
import socket
import ssl

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from conftest import make_donor
from utils import mailer, security


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    crt = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
           .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
           .not_valid_after(now + datetime.timedelta(days=2))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
           .sign(key, hashes.SHA256()))
    d = tmp_path_factory.mktemp("tls")
    (d / "c.pem").write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    (d / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
    return d / "c.pem", d / "k.pem"


def body_text(envelope):
    """The readable message text, the way a mail app shows it (long lines are decoded, not split)."""
    return email.message_from_bytes(envelope.content).get_payload(decode=True).decode()


class Inbox:
    def __init__(self):
        self.mail = []

    async def handle_DATA(self, server, session, envelope):
        self.mail.append(envelope)
        return "250 OK"


def _authenticator(server, session, envelope, mechanism, auth_data):
    ok = isinstance(auth_data, LoginPassword) and auth_data.login == b"mailer" and auth_data.password == b"s3cret"
    return AuthResult(success=ok)


def _start(cert, implicit_ssl):
    crt, key = cert
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(crt, key)
    inbox, port = Inbox(), _free_port()
    kwargs = dict(ssl_context=server_ctx) if implicit_ssl else dict(tls_context=server_ctx, require_starttls=True)
    ctl = Controller(inbox, hostname="127.0.0.1", port=port, authenticator=_authenticator, auth_required=True,
                     auth_require_tls=not implicit_ssl, **kwargs)       # implicit SSL is already encrypted
    ctl.start()
    return ctl, inbox, port


@pytest.fixture(params=["starttls", "ssl"])
def smtp(request, app, cert, monkeypatch):
    ctl, inbox, port = _start(cert, implicit_ssl=request.param == "ssl")
    trust = ssl.create_default_context(cafile=str(cert[0]))
    monkeypatch.setattr(mailer, "_tls_context", lambda: trust)               # trust only our test certificate
    app.config.update(TESTING=False, SMTP_HOST="127.0.0.1", SMTP_PORT=port, SMTP_USER="mailer", SMTP_PASSWORD="s3cret",
                      SMTP_FROM="BloodLink <noreply@bloodlink.test>", SMTP_SECURITY=request.param,
                      PUBLIC_BASE_URL="http://127.0.0.1:5000")
    yield inbox
    ctl.stop()


def test_password_reset_email_really_arrives(app, client, smtp):
    donor = make_donor("O+")
    client.post("/forgot-password", data={"email": donor.email})
    assert len(smtp.mail) == 1
    mail = smtp.mail[0]
    text = body_text(mail)
    assert mail.rcpt_tos == [donor.email] and "noreply@bloodlink.test" in mail.mail_from
    assert "/reset-password/" in text
    assert email.message_from_bytes(mail.content)["Subject"] == "Reset your BloodLink password"
    link = next(w for w in text.split() if "/reset-password/" in w)
    assert client.get(link).status_code == 200                                # the emailed link works


def test_verification_email_arrives(app, smtp):
    donor = make_donor("A+")
    assert mailer.deliver(donor.email, "Confirm your BloodLink email", f"Open: {security.verify_token('donor', donor)}")
    assert smtp.mail[0].rcpt_tos == [donor.email]


def test_donor_alert_email_respects_opt_in_and_has_an_unsubscribe_link(app, smtp):
    quiet, fan = make_donor("O+"), make_donor("O+")
    fan.email_opt_in = True
    from models import db
    db.session.commit()
    assert mailer.send_donor_email(quiet, "Needs your group", "hello") is False
    assert mailer.send_donor_email(fan, "Needs your group", "hello") is True
    assert [m.rcpt_tos for m in smtp.mail] == [[fan.email]]
    raw = smtp.mail[0].content.decode() if isinstance(smtp.mail[0].content, bytes) else smtp.mail[0].content
    assert "List-Unsubscribe" in raw


def test_wrong_password_does_not_crash_and_sends_nothing(app, smtp):
    app.config["SMTP_PASSWORD"] = "wrong"
    assert mailer.deliver("someone@example.com", "x", "y") is False
    assert smtp.mail == []


def test_unknown_server_certificate_is_refused(app, cert, monkeypatch):
    ctl, inbox, port = _start(cert, implicit_ssl=False)
    try:
        app.config.update(TESTING=False, SMTP_HOST="127.0.0.1", SMTP_PORT=port, SMTP_USER="mailer",
                          SMTP_PASSWORD="s3cret", SMTP_FROM="x@y.z", SMTP_SECURITY="starttls")
        assert mailer.deliver("someone@example.com", "x", "y") is False      # default context does not trust our cert
        assert inbox.mail == []
    finally:
        ctl.stop()


def test_unreachable_server_is_handled(app):
    app.config.update(TESTING=False, SMTP_HOST="127.0.0.1", SMTP_PORT=_free_port(), SMTP_USER="", SMTP_FROM="x@y.z")
    assert mailer.deliver("someone@example.com", "x", "y") is False


def test_port_465_means_ssl_unless_told_otherwise(app, monkeypatch):
    seen = {}
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", lambda *a, **k: seen.setdefault("ssl", True) and (_ for _ in ()).throw(OSError("stop")))
    with pytest.raises(OSError):
        mailer._open_smtp({"SMTP_PORT": 465, "SMTP_HOST": "h", "SMTP_USER": "", "SMTP_PASSWORD": "", "SMTP_SECURITY": ""})
    assert seen == {"ssl": True}


def test_without_smtp_the_dev_link_is_printed_to_the_log(app, client, caplog):
    import logging
    app.config["TESTING"] = False
    donor = make_donor("O+")
    with caplog.at_level(logging.INFO, logger="bloodlink.mail"):
        client.post("/forgot-password", data={"email": donor.email})
    assert "DEV MAIL" in caplog.text and "/reset-password/" in caplog.text
