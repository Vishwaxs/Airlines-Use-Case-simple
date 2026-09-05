from copy import deepcopy
from datetime import datetime, time

# Workbook timestamps have no timezone; these fixtures preserve that source contract.
# ruff: noqa: DTZ001
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from src.clean import clean, flight_timing, passenger_survivors, raw_duration_minutes
from src.ingest import ingest
from src.validate import read_rules, validate


@pytest.fixture(scope="module")
def source_tables(tmp_path_factory):
    return ingest(Path(__file__).resolve().parents[1] / "data/raw/UseCase_Airlines.xlsx",
                  tmp_path_factory.mktemp("bronze"), "test-clean")


@pytest.fixture(scope="module")
def source_result(source_tables):
    return clean(source_tables, validate(source_tables), "test-secret-only")


@pytest.fixture
def tiny_tables():
    rows = {
        "flights": {"flight_id": "AI001", "airline": "Air India", "source": "DEL", "destination": "BLR",
                    "departure_time": datetime(2026, 4, 19, 23, 30),
                    "arrival_time": datetime(2026, 4, 20, 1, 15), "duration": time(1, 45)},
        "bookings": {"booking_id": "B0001", "passenger_id": "P0001", "flight_id": "AI001",
                     "booking_date": datetime(2026, 3, 1), "status": "CONFIRMED", "passport_number": "TEST_ONLY",
                     "seat_number": "1A", "emergency_contact_name": "Example", "emergency_contact_phone": "0000000000"},
        "payments": {"payment_id": "PAY0001", "booking_id": "B0001", "amount": 100.01, "payment_method": "UPI"},
        "passengers": {"passenger_id": "P0001", "first_name": "Asha", "last_name": "Example", "age": 25,
                       "gender": "F", "email": "asha@example.invalid", "phone": "+91-0000000000",
                       "aadhaar_id": "000123456789", "date_of_birth": datetime(2001, 1, 1)},
    }
    return {name: pd.DataFrame([dict(row, source_row=2, source_sheet=name, run_id="test",
                                    ingested_at="2026-09-05T00:00:00+00:00")]) for name, row in rows.items()}


def test_source_counts_and_duplicate_treatment(source_result):
    silver, quarantine, issues, audit = source_result
    assert {name: len(frame) for name, frame in silver.items()} == {
        "flights": 1003, "bookings": 1000, "payments": 1000, "passengers": 1000}
    assert silver["flights"].flight_id.is_unique
    assert quarantine["flights"].flight_id.tolist() == ["6F250", "6F250"]
    assert set(quarantine["flights"].quarantine_reason) == {"conflicting_duplicate_key"}
    assert len(silver["bookings"][silver["bookings"].flight_id == "6F250"]) == 2
    assert (issues.issue == "exact_duplicate").sum() == 15
    assert (issues.issue == "unavailable_flight_reference").sum() == 2
    assert len(audit) == 75
    assert audit.passenger_id.nunique() == 36
    assert audit.is_survivor.sum() == 36


def test_sj192_correction_and_raw_reconciliation(source_result):
    flights = source_result[0]["flights"].set_index("flight_id")
    row = flights.loc["SJ192"]
    assert row.duration_minutes == 300
    assert row.raw_duration_minutes == -1140
    assert row.was_corrected
    assert row.correction_reason == "arrival_rolled_forward_one_day"
    assert not row.duration_matches_raw
    assert not row.is_overnight
    assert not row.is_red_eye
    assert flights.was_corrected.sum() == 1
    assert (~flights.duration_matches_raw).sum() == 1


def test_raw_duration_keeps_subsecond_precision():
    assert raw_duration_minutes(time(2, 0, 0, 299000)) == pytest.approx(120.004983333333)


@pytest.mark.parametrize("difference_seconds,expected", [(0.999, True), (1, True), (1.001, False)])
def test_raw_duration_reconciliation_tolerance(tiny_tables, difference_seconds, expected):
    tiny_tables["flights"].loc[0, "arrival_time"] += pd.Timedelta(microseconds=round(difference_seconds * 1_000_000))
    silver, _, issues, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert silver["flights"].iloc[0].duration_matches_raw == expected
    assert ("duration_reconciliation_mismatch" in set(issues.issue)) == (not expected)


def test_correctly_dated_overnight_flights_are_unchanged(source_tables, source_result):
    original = source_tables["flights"].set_index("source_row")
    cleaned = source_result[0]["flights"]
    for row in cleaned[~cleaned.was_corrected].itertuples():
        assert row.arrival_time == original.loc[row.source_row, "arrival_time"]
    assert cleaned.is_overnight.sum() == 122


def test_valid_next_day_arrival_is_not_shifted():
    arrival = datetime(2026, 4, 20, 1, 15)
    result = flight_timing(datetime(2026, 4, 19, 23, 30), arrival)
    assert result["duration_minutes"] == 105
    assert result["is_overnight"] and result["is_red_eye"]
    assert not result["was_corrected"]
    assert result["arrival_time"] == arrival


def test_red_eye_and_overnight_are_different():
    red_eye = flight_timing(datetime(2026, 4, 20, 2), datetime(2026, 4, 20, 3))
    overnight = flight_timing(datetime(2026, 4, 19, 21), datetime(2026, 4, 20, 1))
    assert red_eye["is_red_eye"] and not red_eye["is_overnight"]
    assert overnight["is_overnight"] and not overnight["is_red_eye"]


@pytest.mark.parametrize("hour,expected", [(4, True), (5, False), (21, False), (22, True)])
def test_red_eye_hour_boundaries(hour, expected):
    departure = pd.Timestamp(2026, 4, 19, hour)
    assert flight_timing(departure, departure + pd.Timedelta(minutes=30))["is_red_eye"] == expected


def test_source_payment_quality_and_exact_total(source_tables, source_result):
    payments = source_result[0]["payments"]
    assert payments.groupby("amount_quality").size().to_dict() == {"valid": 922, "missing": 48, "non_numeric": 30}
    assert payments.loc[payments.amount_quality != "valid", "amount"].isna().all()
    assert payments.loc[payments.amount_quality != "valid", "amount_cents"].isna().all()
    independently_summed = sum(Decimal(str(value)) for value in source_tables["payments"].amount
                              if isinstance(value, (int, float)))
    assert independently_summed == Decimal("7385142.98")
    assert payments.amount_cents.sum() == int(independently_summed * 100)


def test_source_survivorship_is_independent_of_dataframe_order(source_tables, source_result):
    passengers = source_tables["passengers"].sample(frac=1, random_state=22)
    survivors, audit = passenger_survivors(passengers, read_rules()["required_columns"]["passengers"])
    pd.testing.assert_frame_equal(audit.reset_index(drop=True), source_result[3].reset_index(drop=True))
    expected = source_result[0]["passengers"].set_index("passenger_id").source_row.sort_index()
    pd.testing.assert_series_equal(survivors.set_index("passenger_id").source_row.sort_index(), expected)


def test_survivorship_priority_is_explicit(tiny_tables):
    first = tiny_tables["passengers"].iloc[0].to_dict()
    candidates = [dict(first, source_row=2, last_name=None, email="a@example.invalid"),
                  dict(first, source_row=3, aadhaar_id="123456789", email="a@example.invalid"),
                  dict(first, source_row=4, email="z@example.invalid"),
                  dict(first, source_row=5, email="b@example.invalid"),
                  dict(first, source_row=6, email="b@example.invalid")]
    survivors, audit = passenger_survivors(pd.DataFrame(candidates), read_rules()["required_columns"]["passengers"])
    assert survivors.source_row.tolist() == [5]
    assert audit.candidate_source_row.tolist() == [5, 6, 4, 3, 2]
    assert set(audit.rule_used) == {"lowest_source_row_tiebreak"}
    assert not {"email", "aadhaar_id", "phone", "first_name", "last_name"} & set(audit.columns)


def test_incomplete_records_are_retained(tiny_tables):
    tiny_tables["flights"].loc[0, "airline"] = None
    tiny_tables["bookings"].loc[0, "status"] = None
    tiny_tables["payments"]["amount"] = [None]
    tiny_tables["passengers"].loc[0, "last_name"] = None
    tiny_tables["passengers"].loc[0, "aadhaar_id"] = None
    silver, quarantine, issues, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert all(len(frame) == 1 for frame in silver.values())
    assert all(frame.empty for frame in quarantine.values())
    assert silver["flights"].iloc[0].airline == "UNKNOWN"
    assert silver["flights"].iloc[0].is_unknown
    assert silver["bookings"].iloc[0].status == "UNKNOWN"
    assert not silver["bookings"].iloc[0].is_valid
    assert silver["payments"].iloc[0].amount_quality == "missing"
    assert silver["passengers"].iloc[0].masked_name == "A***"
    assert silver["passengers"].iloc[0].is_identity_fallback
    assert {"missing_airline", "missing_status", "missing_amount", "missing_last_name"} <= set(issues.issue)


def test_missing_and_sentinel_categories_stay_separate(tiny_tables):
    tiny_tables["flights"].loc[0, "airline"] = "UNKNOWN"
    tiny_tables["bookings"].loc[0, "status"] = "INVALID"
    tiny_tables["payments"]["amount"] = ["INVALID"]
    silver, _, issues, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert {"sentinel_airline", "sentinel_status", "non_numeric_amount"} <= set(issues.issue)
    assert not {"missing_airline", "missing_status", "missing_amount"} & set(issues.issue)
    assert silver["payments"].iloc[0].amount_quality == "non_numeric"
    assert pd.isna(silver["payments"].iloc[0].amount)


@pytest.mark.parametrize("source_status,expected,valid", [(" confirmed ", "CONFIRMED", True),
                                                          ("pending", "PENDING", True),
                                                          ("BAD", "INVALID", False)])
def test_status_normalization_preserves_bookings(tiny_tables, source_status, expected, valid):
    tiny_tables["bookings"].loc[0, "status"] = source_status
    silver, _, issues, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert len(silver["bookings"]) == 1
    assert silver["bookings"].iloc[0].status == expected
    assert silver["bookings"].iloc[0].is_valid == valid
    assert ("unexpected_status" in set(issues.issue)) == (not valid)


@pytest.mark.parametrize("arrival", [datetime(2026, 4, 18, 1), datetime(2026, 4, 22, 1), "not-a-date", 123])
def test_unusable_flight_is_quarantined_without_losing_booking(tiny_tables, arrival):
    tiny_tables["flights"]["arrival_time"] = [arrival]
    silver, quarantine, issues, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert silver["flights"].empty
    assert len(quarantine["flights"]) == 1
    assert len(silver["bookings"]) == 1
    assert "unavailable_flight_reference" in set(issues.issue)


def test_orphan_payment_is_quarantined(tiny_tables):
    tiny_tables["payments"].loc[0, "booking_id"] = "B9999"
    silver, quarantine, _, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert silver["payments"].empty
    assert quarantine["payments"].quarantine_reason.tolist() == ["missing_booking_reference"]


def test_payment_for_quarantined_booking_is_quarantined(tiny_tables):
    tiny_tables["bookings"]["booking_date"] = ["not-a-date"]
    silver, quarantine, _, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert silver["bookings"].empty
    assert silver["payments"].empty
    assert quarantine["payments"].quarantine_reason.tolist() == ["unavailable_booking_reference"]


def test_numeric_booking_timestamp_is_quarantined(tiny_tables):
    tiny_tables["bookings"]["booking_date"] = [123]
    silver, quarantine, _, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert silver["bookings"].empty
    assert quarantine["bookings"].quarantine_reason.tolist() == ["invalid_timestamp"]


@pytest.mark.parametrize("amount", [-10, 10.001])
def test_unusable_numeric_amount_is_quarantined(tiny_tables, amount):
    tiny_tables["payments"]["amount"] = [amount]
    silver, quarantine, _, _ = clean(tiny_tables, validate(tiny_tables), "test-secret")
    assert silver["payments"].empty
    assert quarantine["payments"].quarantine_reason.tolist() == ["invalid_amount_range"]


def test_schema_failure_stops_before_cleaning(tiny_tables):
    with pytest.raises(ValueError, match="Missing required sheets"):
        validate({name: frame for name, frame in tiny_tables.items() if name != "payments"})
    tiny_tables["flights"] = tiny_tables["flights"].drop(columns="arrival_time")
    with pytest.raises(ValueError, match="Missing columns in flights"):
        validate(tiny_tables)


def test_silver_removes_source_contacts_and_dob(source_result):
    sensitive = {"first_name", "last_name", "email", "phone", "aadhaar_id", "date_of_birth",
                 "passport_number", "emergency_contact_name", "emergency_contact_phone"}
    for frame in source_result[0].values():
        assert not sensitive.intersection(frame.columns)


def test_clean_does_not_mutate_bronze(tiny_tables):
    before = deepcopy(tiny_tables)
    clean(tiny_tables, validate(tiny_tables), "test-secret")
    for name in tiny_tables:
        pd.testing.assert_frame_equal(tiny_tables[name], before[name])
