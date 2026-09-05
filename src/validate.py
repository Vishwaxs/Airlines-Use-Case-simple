import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import yaml

from src.pii import normalize_aadhaar

ISSUE_COLUMNS = ["table_name", "source_row", "record_id", "issue", "treatment"]
METADATA_COLUMNS = ["source_row", "source_sheet", "run_id", "ingested_at"]
PRIMARY_KEYS = {"flights": "flight_id", "bookings": "booking_id",
                "payments": "payment_id", "passengers": "passenger_id"}


def read_rules(rules_path=None) -> dict:
    path = Path(rules_path) if rules_path else Path(__file__).resolve().parents[1] / "config/validation_rules.yaml"
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def is_missing(value) -> bool:
    return value is None or pd.isna(value) or (isinstance(value, str) and not value.strip())


def parse_timestamp(value):
    if not isinstance(value, (str, date, datetime, pd.Timestamp)) or is_missing(value):
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce")
    # The workbook uses local, timezone-free timestamps throughout.
    return pd.NaT if not pd.isna(parsed) and parsed.tzinfo is not None else parsed


def normalize_booking_status(value, accepted_statuses: list[str]) -> str:
    if is_missing(value):
        return "UNKNOWN"
    status = str(value).strip().upper()
    return status if status in accepted_statuses else "INVALID"


def classify_amount(value) -> tuple[str, int | None]:
    """Convert usable rupee amounts to integer cents without binary float summation."""
    if is_missing(value):
        return "missing", None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "non_numeric", None
    if not number.is_finite():
        return "non_numeric", None
    cents = number * 100
    if number < 0 or cents != cents.to_integral_value() or cents > 999999999999999999:
        return "out_of_range", None
    return "valid", int(cents)


def validate(tables: dict[str, pd.DataFrame], rules_path=None) -> pd.DataFrame:
    """Fail on missing structure; return row issues with no source contact details."""
    rules = read_rules(rules_path)
    missing_sheets = set(rules["required_columns"]) - set(tables)
    if missing_sheets:
        raise ValueError("Missing required sheets: " + ", ".join(sorted(missing_sheets)))
    for table_name, required in rules["required_columns"].items():
        frame = tables[table_name]
        missing = set(required + METADATA_COLUMNS) - set(frame.columns)
        if missing:
            raise ValueError(f"Missing columns in {table_name}: {', '.join(sorted(missing))}")
        if frame.empty:
            raise ValueError(f"Required sheet is empty: {table_name}")

    events = []
    flight_ids = set(tables["flights"].flight_id)
    passenger_ids = set(tables["passengers"].passenger_id)
    booking_ids = set(tables["bookings"].booking_id)
    booked_flights = set(tables["bookings"].flight_id)
    paid_bookings = set(tables["payments"].booking_id)

    def add(table_name, row, issue, treatment):
        record_id = row[PRIMARY_KEYS[table_name]]
        # Invalid key contents may themselves contain private data.
        pattern = rules["id_patterns"][PRIMARY_KEYS[table_name]]
        safe_id = str(record_id) if re.fullmatch(pattern, str(record_id)) else "INVALID_KEY"
        events.append([table_name, int(row["source_row"]), safe_id, issue, treatment])

    for table_name, key in PRIMARY_KEYS.items():
        frame = tables[table_name]
        for _, row in frame.iterrows():
            if not re.fullmatch(rules["id_patterns"][key], str(row[key])):
                add(table_name, row, "invalid_primary_key", "quarantine")
        if table_name in ("bookings", "payments"):
            for _, row in frame[frame.duplicated(key, keep=False)].iterrows():
                add(table_name, row, "duplicate_primary_key", "quarantine")

    flights = tables["flights"]
    business = rules["required_columns"]["flights"]
    for _, group in flights.groupby("flight_id", dropna=False, sort=False):
        if len(group) > 1:
            if len(group[business].drop_duplicates()) == 1:
                for _, row in group.sort_values("source_row").iloc[1:].iterrows():
                    add("flights", row, "exact_duplicate", "exact_duplicate_removed")
            else:
                for _, row in group.iterrows():
                    add("flights", row, "conflicting_duplicate_key", "quarantine")
    for _, row in flights.iterrows():
        if is_missing(row.airline):
            add("flights", row, "missing_airline", "retain_as_unknown")
        elif str(row.airline).strip().upper() == "UNKNOWN":
            add("flights", row, "sentinel_airline", "retain_as_unknown")
        elif row.airline not in rules["airlines"]:
            add("flights", row, "unexpected_airline", "retain_as_unknown")
        if any(not re.fullmatch(r"[A-Z]{3}", str(row[col])) for col in ("source", "destination")):
            add("flights", row, "invalid_route", "quarantine")
        elif row.source == row.destination:
            add("flights", row, "self_route", "quarantine")
        departure = parse_timestamp(row.departure_time)
        arrival = parse_timestamp(row.arrival_time)
        if pd.isna(departure) or pd.isna(arrival):
            add("flights", row, "invalid_timestamp", "quarantine")
        else:
            minutes = (arrival - departure).total_seconds() / 60
            if minutes < 0:
                add("flights", row, "negative_duration", "roll_arrival_forward_one_day")
                minutes += 1440
            if minutes <= 0 or minutes > rules["maximum_duration_minutes"]:
                add("flights", row, "invalid_duration", "quarantine")
        if row.flight_id not in booked_flights:
            add("flights", row, "flight_without_booking", "retain")

    for _, row in tables["bookings"].iterrows():
        if pd.isna(parse_timestamp(row.booking_date)):
            add("bookings", row, "invalid_timestamp", "quarantine")
        if is_missing(row.status):
            add("bookings", row, "missing_status", "retain_as_unknown")
        elif str(row.status).strip().upper() == "INVALID":
            add("bookings", row, "sentinel_status", "retain_as_invalid")
        elif normalize_booking_status(row.status, rules["booking_statuses"]) == "INVALID":
            add("bookings", row, "unexpected_status", "retain_as_invalid")
        if row.flight_id not in flight_ids:
            add("bookings", row, "missing_flight_reference", "retain_with_unknown_flight")
        if row.passenger_id not in passenger_ids:
            add("bookings", row, "missing_passenger_reference", "retain_with_unknown_passenger")
        if row.booking_id not in paid_bookings:
            add("bookings", row, "booking_without_payment", "retain")

    for _, row in tables["payments"].iterrows():
        quality, _ = classify_amount(row.amount)
        if quality != "valid":
            issue = {"missing": "missing_amount", "non_numeric": "non_numeric_amount",
                     "out_of_range": "invalid_amount_range"}[quality]
            add("payments", row, issue, "quarantine" if quality == "out_of_range" else "retain_with_null_amount")
        if is_missing(row.payment_method) or row.payment_method not in rules["payment_methods"]:
            add("payments", row, "unexpected_payment_method", "retain_as_unknown")
        if row.booking_id not in booking_ids:
            add("payments", row, "missing_booking_reference", "quarantine")

    passengers = tables["passengers"]
    for _, row in passengers[passengers.duplicated("passenger_id", keep=False)].iterrows():
        add("passengers", row, "duplicate_passenger_id", "deterministic_survivorship")
    for _, row in passengers.iterrows():
        if is_missing(row.last_name):
            add("passengers", row, "missing_last_name", "mask_available_name")
        if is_missing(row.first_name):
            add("passengers", row, "missing_first_name", "mask_available_name")
        if not re.fullmatch(r"[0-9]{12}", str(row.aadhaar_id)):
            add("passengers", row, "aadhaar_length_anomaly",
                "normalize_before_hmac" if normalize_aadhaar(row.aadhaar_id) else "tokenize_source_id_fallback")
        age = pd.to_numeric(row.age, errors="coerce")
        if pd.isna(age) or age < rules["age_min"] or age > rules["age_max"] or float(age) % 1:
            add("passengers", row, "invalid_age", "retain_with_null_age")
        if is_missing(row.gender) or row.gender not in rules["genders"]:
            add("passengers", row, "unexpected_gender", "retain_as_unknown")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(row.email)):
            add("passengers", row, "invalid_email", "remove_from_silver")
        if not re.fullmatch(r"(?:\+91-)?[0-9]{10}", str(row.phone)):
            add("passengers", row, "invalid_phone", "remove_from_silver")
        if pd.isna(parse_timestamp(row.date_of_birth)):
            add("passengers", row, "invalid_date_of_birth", "remove_from_silver")

    return pd.DataFrame(events, columns=ISSUE_COLUMNS)
