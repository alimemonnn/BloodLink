"""Spot chat messages that ask for money or move the conversation off BloodLink.

Blood must never be bought or sold. A flagged message is still delivered (we could be wrong), but
the sender is told why it is a problem, the other people see a warning, and administrators get a
report to review. Rules only: no outside service reads the message.
"""
import re

_PATTERNS = [
    ("asks for payment", re.compile(r"\b(?:pay(?:ment|ing)?|paid|advance|charges?|fees?|price|cost|rs\.?\s*\d|rupees?|pkr|per bag|"
                                    r"send (?:me )?(?:money|cash)|transfer|cash)\b", re.I)),
    ("mentions a payment app or bank", re.compile(r"\b(?:easypaisa|easy paisa|jazz ?cash|sadapay|nayapay|bkash|paypal|"
                                                    r"western union|bank account|account number|iban|swift)\b", re.I)),
    ("shares an account or card number", re.compile(r"\b(?:PK\d{2}[A-Z]{4}\d{16}|\d{13,19})\b")),
    ("sends a link", re.compile(r"(?:https?://|www\.|bit\.ly|t\.me/|wa\.me/)", re.I)),
    ("asks to move to another app", re.compile(r"\b(?:whatsapp me|text me on|call me on|telegram|dm me)\b", re.I)),
]
ADVICE = ("This message mentions money or an outside link. BloodLink is free and blood must never be bought or sold. "
          "Do not send money or share account details.")


def scan(text):
    """Return a list of short reasons (empty when the message looks fine)."""
    text = text or ""
    return [reason for reason, pattern in _PATTERNS if pattern.search(text)]
