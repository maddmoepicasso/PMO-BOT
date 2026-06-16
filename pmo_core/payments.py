from __future__ import annotations

from typing import Any


def text_has_sensitive_terms(*values: Any) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    blocked_terms = ["password", "passwd", "ssn", "social security", "cvv", "cvc", "card number", "routing number", "account number", "seed phrase", "private key"]
    return any(term in text for term in blocked_terms)
