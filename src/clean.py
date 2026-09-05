import re
from datetime import datetime, time, timedelta
from decimal import Decimal

import pandas as pd
from openpyxl.utils.datetime import to_excel

from src.pii import age_band, masked_name, normalize_aadhaar, passenger_token
from src.validate import (
    ISSUE_COLUMNS,
    METADATA_COLUMNS,
    PRIMARY_KEYS,
    classify_amount,
    is_missing,
    normalize_booking_status,
    read_rules,
)


def raw_duration_minutes(value) -> float | None:
    """Read Excel duration cells for comparison; timestamps remain authoritative."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return round(to_excel(value) * 1440, 6)
    if isinstance(value, time):
        return value.hour * 60 + value.minute + value.second / 60 + value.microsecond / 60_000_000
    if isinstance(value, timedelta):
        return value.total_seconds() / 60
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return round(value * 1440, 6)
    parsed = pd.to_timedelta(str(value), errors="coerce")
    return None if pd.isna(parsed) else parsed.total_seconds() / 60


def flight_timing(departure, arrival) -> dict:
    """Repair a negative interval once, then derive separate timing indicators."""
    departure = pd.Timestamp(departure)
    arrival = pd.Timestamp(arrival)
    was_corrected = arrival < departure
    if was_corrected:
        arrival += pd.Timedelta(days=1)
    minutes = (arrival - departure).total_seconds() / 60
    if not 0 < minutes <= 1440:
        raise ValueError("Flight duration must be greater than zero and at most 1440 minutes")
    return {
        "departure_time": departure,
        "arrival_time": arrival,
        "duration_minutes": minutes,
        "was_corrected": was_corrected,
        "correction_reason": "arrival_rolled_forward_one_day" if was_corrected else None,
        "is_overnight": departure.date() != arrival.date(),
        "is_red_eye": departure.hour >= 22 or departure.hour < 5,
    }


def passenger_survivors(frame: pd.DataFrame, business_columns: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Choose duplicate candidates by completeness, Aadhaar shape, email, then row."""
    ranked = frame.copy()
    ranked["_nulls"] = ranked[business_columns].apply(lambda col: col.map(is_missing)).sum(axis=1)
    ranked["_aadhaar_ok"] = ranked.aadhaar_id.map(lambda value: bool(re.fullmatch(r"[0-9]{12}", str(value))))
    ranked["_email_order"] = ranked.email.map(lambda value: "\uffff" if is_missing(value) else str(value))
    ranked = ranked.sort_values(["passenger_id", "_nulls", "_aadhaar_ok", "_email_order", "source_row"],
                                ascending=[True, True, False, True, True], kind="stable")
    selected_rows = []
    audit = []
    for passenger_id, group in ranked.groupby("passenger_id", sort=True):
        selected_rows.append(group.index[0])
        if len(group) == 1:
            continue
        remaining = group[group._nulls == group._nulls.min()]
        rule = "fewest_nulls"
        if len(remaining) > 1:
            remaining = remaining[remaining._aadhaar_ok == remaining._aadhaar_ok.max()]
            rule = "expected_aadhaar_length"
        if len(remaining) > 1:
            remaining = remaining[remaining._email_order == remaining._email_order.min()]
            rule = "lexicographic_email"
        if len(remaining) > 1:
            rule = "lowest_source_row_tiebreak"
        for rank, (_, row) in enumerate(group.iterrows(), start=1):
            audit.append({"passenger_id": passenger_id, "candidate_source_row": int(row.source_row),
                          "candidate_count": len(group), "null_count": int(row._nulls),
                          "aadhaar_has_expected_length": bool(row._aadhaar_ok), "candidate_rank": rank,
                          "is_survivor": rank == 1, "rule_used": rule})
    columns = ["passenger_id", "candidate_source_row", "candidate_count", "null_count",
               "aadhaar_has_expected_length", "candidate_rank", "is_survivor", "rule_used"]
    return frame.loc[selected_rows].copy(), pd.DataFrame(audit, columns=columns)


def clean(tables: dict[str, pd.DataFrame], issues: pd.DataFrame, pepper: str,
          rules_path=None) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame]:
    """Return PII-reduced silver, restricted quarantine, issue events, and survivor audit."""
    # Fail before creating partial output when the required secret is absent.
    passenger_token("000000000001", pepper)
    rules = read_rules(rules_path)
    events = issues.to_dict("records")
    silver = {}
    quarantine = {}
    usable = {}

    for table_name, frame in tables.items():
        if table_name not in PRIMARY_KEYS:
            continue
        rejected = issues[(issues.table_name == table_name) & (issues.treatment == "quarantine")]
        reasons = rejected.groupby("source_row").issue.agg(lambda values: ";".join(sorted(set(values))))
        mask = frame.source_row.isin(reasons.index)
        quarantine[table_name] = frame.loc[mask].copy()
        quarantine[table_name]["quarantine_reason"] = quarantine[table_name].source_row.map(reasons)
        usable[table_name] = frame.loc[~mask].copy()

    def add(table_name, row, issue, treatment):
        events.append(dict(zip(ISSUE_COLUMNS, [table_name, int(row.source_row),
                                               row[PRIMARY_KEYS[table_name]], issue, treatment])))

    flights = usable["flights"]
    duplicate_rows = issues[(issues.table_name == "flights") & (issues.issue == "exact_duplicate")].source_row
    flights = flights[~flights.source_row.isin(duplicate_rows)].copy()
    flight_records = []
    for _, row in flights.sort_values("flight_id").iterrows():
        record = {col: row[col] for col in ["flight_id", "source", "destination"] + METADATA_COLUMNS}
        airline = "UNKNOWN" if is_missing(row.airline) or row.airline not in rules["airlines"] else row.airline
        record.update(airline=airline, is_unknown=airline == "UNKNOWN")
        record.update(flight_timing(row.departure_time, row.arrival_time))
        raw_minutes = raw_duration_minutes(row.duration)
        difference_seconds = None if raw_minutes is None else round(abs(record["duration_minutes"] - raw_minutes) * 60, 6)
        matches = None if difference_seconds is None else difference_seconds <= rules["duration_reconciliation_tolerance_seconds"]
        record.update(raw_duration_minutes=raw_minutes, duration_matches_raw=matches)
        if raw_minutes is None:
            add("flights", row, "unparseable_raw_duration", "retain_timestamp_duration")
        elif not matches:
            add("flights", row, "duration_reconciliation_mismatch", "retain_timestamp_duration")
        flight_records.append(record)
    flight_columns = ["flight_id", "source", "destination"] + METADATA_COLUMNS + [
        "airline", "is_unknown", "departure_time", "arrival_time", "duration_minutes", "was_corrected",
        "correction_reason", "is_overnight", "is_red_eye", "raw_duration_minutes", "duration_matches_raw"]
    silver["flights"] = pd.DataFrame(flight_records, columns=flight_columns)
    for column in ["departure_time", "arrival_time"]:
        silver["flights"][column] = pd.to_datetime(silver["flights"][column])
    for column in ["was_corrected", "is_overnight", "is_red_eye", "is_unknown"]:
        silver["flights"][column] = silver["flights"][column].astype(bool)
    silver["flights"]["duration_minutes"] = silver["flights"].duration_minutes.astype(float)
    silver["flights"]["duration_matches_raw"] = silver["flights"].duration_matches_raw.astype("boolean")

    passengers, survivorship = passenger_survivors(usable["passengers"], rules["required_columns"]["passengers"])
    passenger_records = []
    for _, row in passengers.iterrows():
        age = pd.to_numeric(row.age, errors="coerce")
        if pd.isna(age) or age < rules["age_min"] or age > rules["age_max"] or float(age) % 1:
            age = None
        record = {col: row[col] for col in ["passenger_id"] + METADATA_COLUMNS}
        record.update(passenger_token=passenger_token(row.aadhaar_id, pepper, row.passenger_id),
                      masked_name=masked_name(row.first_name, row.last_name), age=age,
                      age_band=age_band(age), gender=row.gender if not is_missing(row.gender) and row.gender in rules["genders"] else "UNKNOWN",
                      is_identity_fallback=normalize_aadhaar(row.aadhaar_id) is None,
                      had_missing_last_name=is_missing(row.last_name))
        passenger_records.append(record)
    passenger_columns = ["passenger_id"] + METADATA_COLUMNS + ["passenger_token", "masked_name", "age", "age_band",
                         "gender", "is_identity_fallback", "had_missing_last_name"]
    silver["passengers"] = pd.DataFrame(passenger_records, columns=passenger_columns)
    silver["passengers"]["age"] = silver["passengers"].age.astype("Int64")

    bookings = usable["bookings"][["booking_id", "passenger_id", "flight_id", "booking_date", "status"] + METADATA_COLUMNS].copy()
    bookings["booking_date"] = pd.to_datetime(bookings.booking_date)
    bookings["status"] = bookings.status.map(lambda value: normalize_booking_status(value, rules["booking_statuses"]))
    bookings["is_valid"] = bookings.status.isin(rules["booking_statuses"])
    surviving_flights = set(silver["flights"].flight_id)
    source_flights = set(tables["flights"].flight_id)
    surviving_passengers = set(silver["passengers"].passenger_id)
    source_passengers = set(tables["passengers"].passenger_id)
    for _, row in bookings.iterrows():
        if row.flight_id not in surviving_flights and row.flight_id in source_flights:
            add("bookings", row, "unavailable_flight_reference", "retain_with_unknown_flight")
        if row.passenger_id not in surviving_passengers and row.passenger_id in source_passengers:
            add("bookings", row, "unavailable_passenger_reference", "retain_with_unknown_passenger")
    silver["bookings"] = bookings.sort_values("booking_id").reset_index(drop=True)

    payments = usable["payments"].copy()
    orphaned = ~payments.booking_id.isin(bookings.booking_id)
    if orphaned.any():
        newly_rejected = payments[orphaned].copy()
        newly_rejected["quarantine_reason"] = "unavailable_booking_reference"
        quarantine["payments"] = pd.concat([quarantine["payments"], newly_rejected], ignore_index=True)
        for _, row in newly_rejected.iterrows():
            add("payments", row, "unavailable_booking_reference", "quarantine")
        payments = payments[~orphaned].copy()
    classified = payments.amount.map(classify_amount)
    payments["amount_quality"] = classified.map(lambda value: value[0])
    payments["amount_cents"] = pd.array(classified.map(lambda value: value[1]), dtype="Int64")
    # Decimal values keep the exported rupees exact; SQL uses amount_cents as authority.
    payments["amount"] = payments.amount_cents.map(lambda value: None if pd.isna(value) else Decimal(int(value)) / 100)
    payments["payment_method"] = payments.payment_method.where(payments.payment_method.isin(rules["payment_methods"]), "UNKNOWN")
    silver["payments"] = payments[["payment_id", "booking_id", "amount", "amount_cents", "amount_quality", "payment_method"]
                                  + METADATA_COLUMNS].sort_values("payment_id").reset_index(drop=True)
    updated_issues = pd.DataFrame(events, columns=ISSUE_COLUMNS).drop_duplicates().reset_index(drop=True)
    return silver, quarantine, updated_issues, survivorship
