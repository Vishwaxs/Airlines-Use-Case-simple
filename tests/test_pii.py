import hashlib
import hmac

import pandas as pd
import pytest

from src.pii import age_band, masked_name, normalize_aadhaar, passenger_token


def test_leading_zeroes_restored_before_hmac():
    pepper = "test-secret-only"
    expected = hmac.new(pepper.encode(), b"000123456789", hashlib.sha256).hexdigest()
    assert passenger_token(123456789, pepper) == expected
    assert passenger_token(123456789.0, pepper) == expected
    assert passenger_token("123456789", pepper) == expected
    assert passenger_token("000123456789", pepper) == expected
    assert passenger_token("000123456789", "another-test-secret") != expected


@pytest.mark.parametrize("value", [None, pd.NA, "", "NOT_AN_ID", "1234567890123", 123.5])
def test_invalid_identity_is_not_silently_normalized(value):
    assert normalize_aadhaar(value) is None


def test_missing_identity_uses_separate_source_id_namespace():
    assert passenger_token(None, "test-secret", "P0001") == passenger_token(None, "test-secret", "P0001")
    assert passenger_token(None, "test-secret", "P0001") != passenger_token(None, "test-secret", "P0002")
    with pytest.raises(ValueError, match="usable Aadhaar"):
        passenger_token(None, "test-secret")


@pytest.mark.parametrize("pepper", [None, "", "  "])
def test_secret_is_required(pepper):
    with pytest.raises(ValueError, match="ASG_PII_PEPPER"):
        passenger_token("000123456789", pepper)


def test_name_mask_uses_available_name():
    assert masked_name("Asha", None) == "A***"
    assert masked_name("Asha", "Example") == "A*** E***"
    assert masked_name(None, pd.NA) == "UNKNOWN"


@pytest.mark.parametrize("age,expected", [(None, "UNKNOWN"), (17, "0-17"), (18, "18-34"),
                                        (34, "18-34"), (35, "35-59"), (59, "35-59"), (60, "60+")])
def test_age_band_boundaries(age, expected):
    assert age_band(age) == expected
