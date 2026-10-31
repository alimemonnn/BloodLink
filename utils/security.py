"""Password-reset and email-verification links, and two-factor login (TOTP).

* Links are signed, expire, and a reset link stops working as soon as the
  password changes (it embeds a fingerprint of the current password hash).
* TOTP follows RFC 6238 (SHA-1, 6 digits, 30 s), the format every authenticator
  app understands. The secret is encrypted in the database with a key derived
  from SECRET_KEY, so rotating SECRET_KEY switches 2FA off for everyone.
* Recovery codes are random, shown once, and stored only as keyed hashes.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from models import Admin, Donor, Hospital, Patient

ROLE_MODELS = {"admin": Admin, "donor": Donor, "patient": Patient, "hospital": Hospital}


def find_account(email):
    email = (email or "").lower().strip()
    for role, model in ROLE_MODELS.items():
        user = model.query.filter_by(email=email).first()
        if user:
            return role, user
    return None, None


def load_account(role, user_id):
    model = ROLE_MODELS.get(role)
    return model.query.get(user_id) if model else None


# ---------------------------------------------------------------- signed links
def _signer(salt):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def _fingerprint(user):
    return hashlib.sha256((user.password_hash or "").encode()).hexdigest()[:12]


def reset_token(role, user):
    return _signer("bloodlink-reset").dumps({"r": role, "i": user.id, "p": _fingerprint(user)})


def read_reset_token(token):
    """Return (role, user) for a valid, unused, unexpired link, else (None, None)."""
    try:
        data = _signer("bloodlink-reset").loads(token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE"])
        user = load_account(data["r"], data["i"])
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None, None
    if user is None or not getattr(user, "is_active", True) or data.get("p") != _fingerprint(user):
        return None, None
    return data["r"], user


def verify_token(role, user):
    return _signer("bloodlink-verify").dumps({"r": role, "i": user.id, "e": user.email})


def read_verify_token(token):
    try:
        data = _signer("bloodlink-verify").loads(token, max_age=current_app.config["EMAIL_VERIFY_MAX_AGE"])
        user = load_account(data["r"], data["i"])
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None, None
    if user is None or user.email != data.get("e"):
        return None, None
    return data["r"], user


# ------------------------------------------------------------------------ TOTP
def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret, counter, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_at(secret, at=None, step=30):
    return _hotp(secret, int((at if at is not None else time.time()) // step))


def check_totp(secret, code, last_step=None, at=None, step=30, window=1):
    """Return the matched time step (an int) or None. Re-using a step is refused."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    now_step = int((at if at is not None else time.time()) // step)
    for s in range(now_step - window, now_step + window + 1):
        if hmac.compare_digest(_hotp(secret, s), code):
            if last_step is not None and s <= last_step:
                return None
            return s
    return None


def provisioning_uri(user, secret):
    issuer = current_app.config["TOTP_ISSUER"]
    return f"otpauth://totp/{quote(issuer)}:{quote(user.email)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


def _fernet():
    key = hashlib.sha256(("totp|" + current_app.config["SECRET_KEY"]).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(secret):
    return _fernet().encrypt(secret.encode()).decode()


def unseal(value):
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, AttributeError):
        return None


def user_secret(user):
    return unseal(user.totp_secret) if user.totp_secret else None


# --------------------------------------------------------------- recovery codes
def _code_hash(code):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, code.replace("-", "").lower().encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(n=8):
    codes = []
    for _ in range(n):
        raw = secrets.token_hex(4)
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def store_recovery_codes(user, codes):
    user.recovery_codes = json.dumps([_code_hash(c) for c in codes])


def use_recovery_code(user, code):
    """True (and the code is burnt) when ``code`` is one of the user's unused codes."""
    try:
        hashes = json.loads(user.recovery_codes or "[]")
    except ValueError:
        return False
    h = _code_hash(code or "")
    for known in hashes:
        if hmac.compare_digest(known, h):
            hashes.remove(known)
            user.recovery_codes = json.dumps(hashes)
            return True
    return False


def recovery_codes_left(user):
    try:
        return len(json.loads(user.recovery_codes or "[]"))
    except ValueError:
        return 0
