import hashlib
import hmac
import math
import re

import pandas as pd


def normalize_aadhaar(value) -> str | None:
    """Restore leading zeroes before tokenization; reject unusable identifiers."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,12}", text):
        return None
    return text.zfill(12)


def passenger_token(aadhaar, pepper: str, passenger_id: str | None = None) -> str:
    """HMAC the normalized identity, or a namespaced source ID if identity is absent."""
    if not isinstance(pepper, str) or not pepper.strip():
        raise ValueError("ASG_PII_PEPPER must be set to a non-empty secret")
    normalized = normalize_aadhaar(aadhaar)
    if normalized is None:
        if not passenger_id:
            raise ValueError("A usable Aadhaar or passenger_id is required for tokenization")
        normalized = "passenger_id:" + str(passenger_id)
    return hmac.new(pepper.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def masked_name(first_name, last_name) -> str:
    parts = []
    for value in (first_name, last_name):
        if value is not None and not pd.isna(value) and str(value).strip():
            parts.append(str(value).strip()[0] + "***")
    return " ".join(parts) or "UNKNOWN"


def age_band(age) -> str:
    if age is None or pd.isna(age):
        return "UNKNOWN"
    if age < 18:
        return "0-17"
    if age < 35:
        return "18-34"
    if age < 60:
        return "35-59"
    return "60+"
