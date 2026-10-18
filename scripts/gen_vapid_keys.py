"""Create the key pair for browser push notifications. Run once and paste the output into your
environment (Render > Environment). Keep the private key secret.

    python scripts/gen_vapid_keys.py
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


v = Vapid()
v.generate_keys()
private = v.private_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption())
public = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print("VAPID_PUBLIC_KEY=" + b64(public))
print("VAPID_PRIVATE_KEY=" + b64(private))
print("VAPID_SUBJECT=mailto:you@example.com   # change to a real contact address")
