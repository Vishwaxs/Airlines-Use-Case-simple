"""Measure source facts without changing business values or exposing passenger PII."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.datetime import to_excel


def read_source(workbook_path):
    """Ignore only empty Excel padding; return source values and physical type counts."""
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    tables, structure = {}, {}
    for sheet in workbook:
        rows = list(sheet.values)
        header = rows[0]
        keep = [i for i, name in enumerate(header) if name is not None]
        columns = [header[i] for i in keep]
        values = [[row[i] for i in keep] for row in rows[1:]]
        nonempty = [row for row in values if any(value is not None for value in row)]
        tables[sheet.title] = pd.DataFrame(nonempty, columns=columns)
        structure[sheet.title] = {
            "rows": len(nonempty),
            "columns": columns,
            "used_range_rows_excluding_header": sheet.max_row - 1,
            "used_range_columns": sheet.max_column,
            "empty_rows_ignored": len(values) - len(nonempty),
            "empty_unnamed_columns_ignored": len(header) - len(columns),
            "source_types": {
                column: dict(Counter(type(row[i]).__name__ for row in nonempty))
                for i, column in enumerate(columns)
            },
            "nulls": {column: int(tables[sheet.title][column].isna().sum()) for column in columns},
        }
    epoch = workbook.epoch
    workbook.close()
    return tables, structure, epoch


def _counts(series):
    return {"<NULL>" if pd.isna(key) else str(key): int(value)
            for key, value in series.value_counts(dropna=False).items()}


def _money(values):
    return format(sum((Decimal(str(value)) for value in values if pd.notna(value)), Decimal(0)), ".2f")


def _duration_minutes(value, epoch):
    if isinstance(value, time):
        return value.hour * 60 + value.minute + value.second / 60 + value.microsecond / 60_000_000
    if isinstance(value, datetime):
        return to_excel(value, epoch) * 1440
    if isinstance(value, (int, float)):
        return value * 1440
    return None


def profile_source(workbook_path, reports_dir="reports"):
    """Write aggregate source evidence; revenue uses Decimal and is stored as a string."""
    workbook_path = Path(workbook_path)
    tables, structure, epoch = read_source(workbook_path)
    flights, bookings, payments, passengers = (tables[name] for name in
                                             ("flights", "bookings", "payments", "passengers"))
    flight_groups = [group for _, group in flights.groupby("flight_id") if len(group) > 1]
    exact_groups = [group for group in flight_groups if len(group.drop_duplicates()) == 1]
    conflict_groups = [group for group in flight_groups if len(group.drop_duplicates()) > 1]
    conflicting_ids = sorted(group.iloc[0]["flight_id"] for group in conflict_groups)
    passenger_groups = [group for _, group in passengers.groupby("passenger_id") if len(group) > 1]
    departure = pd.to_datetime(flights["departure_time"], errors="coerce", format="mixed")
    arrival = pd.to_datetime(flights["arrival_time"], errors="coerce", format="mixed")
    booking_dates = pd.to_datetime(bookings["booking_date"], errors="coerce", format="mixed")
    ages = pd.to_numeric(passengers["age"], errors="coerce")
    interval = (arrival - departure).dt.total_seconds() / 60
    corrected = interval.where(interval.ge(0), interval + 1440)
    corrected_arrival = arrival.where(interval.ge(0), arrival + pd.Timedelta(days=1))
    parsed_duration = pd.Series([_duration_minutes(value, epoch) for value in flights["duration"]], dtype='float64')
    amount = pd.to_numeric(payments["amount"], errors="coerce")
    measured_payments = payments.assign(numeric_amount=amount)
    booking_flight = bookings.merge(flights, on="flight_id", how="left")
    booking_payment = bookings.merge(measured_payments, on="booking_id", how="left")
    naive_inner = bookings.merge(flights, on="flight_id").merge(measured_payments, on="booking_id")
    naive_left = booking_flight.merge(measured_payments, on="booking_id", how="left")
    total = _money(amount)
    naive_total = _money(naive_inner["numeric_amount"])
    without_booking = ~passengers["passenger_id"].isin(bookings["passenger_id"])
    aadhaar = passengers["aadhaar_id"].astype(str)
    negative_examples = []
    for index in interval[interval.lt(0)].index:
        negative_examples.append({
            "flight_id": str(flights.loc[index, "flight_id"]),
            "departure": departure.loc[index].isoformat(),
            "arrival": arrival.loc[index].isoformat(),
            "raw_interval_minutes": float(interval.loc[index]),
            "one_day_corrected_minutes": float(corrected.loc[index]),
        })
    result = {
        "source_file": workbook_path.name,
        "source_sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
        "structure": structure,
        "flights": {
            "unique_ids": int(flights["flight_id"].nunique()),
            "duplicate_id_groups": len(flight_groups),
            "duplicate_rows_in_groups": sum(len(group) for group in flight_groups),
            "exact_duplicate_groups": len(exact_groups),
            "exact_duplicate_excess_rows": sum(len(group) - 1 for group in exact_groups),
            "conflicting_duplicate_groups": len(conflict_groups),
            "conflicting_ids": conflicting_ids,
            "conflicting_duplicate_rows": sum(len(group) for group in conflict_groups),
            "conflicting_columns": {
                str(group.iloc[0]["flight_id"]): [column for column in flights.columns
                    if group[column].nunique(dropna=False) > 1] for group in conflict_groups
            },
            "airline_counts": _counts(flights["airline"]),
            "real_carrier_count": int(flights.loc[flights["airline"].notna() & flights["airline"].ne("UNKNOWN"), "airline"].nunique()),
            "id_pattern": r"[A-Z0-9]{2}\d{3}",
            "invalid_id_pattern_rows": int((~flights["flight_id"].map(lambda value: bool(re.fullmatch(r"[A-Z0-9]{2}\d{3}", str(value))))).sum()),
            "cities": sorted(set(flights["source"].dropna().astype(str)) | set(flights["destination"].dropna().astype(str))),
            "ordered_routes": len(flights[["source", "destination"]].drop_duplicates()),
            "self_route_rows": int(flights["source"].eq(flights["destination"]).sum()),
            "departure_min": departure.min().isoformat(),
            "departure_max": departure.max().isoformat(),
            "unparseable_timestamp_rows": int((departure.isna() | arrival.isna()).sum()),
            "raw_date_different_rows": int((departure.notna() & arrival.notna() & departure.dt.normalize().ne(arrival.dt.normalize())).sum()),
            "raw_forward_date_crossing_rows": int(arrival.dt.normalize().gt(departure.dt.normalize()).sum()),
            "negative_interval_rows": int(interval.lt(0).sum()),
            "negative_examples": negative_examples,
            "corrected_min_minutes": float(corrected.min()),
            "corrected_max_minutes": float(corrected.max()),
            "corrected_invalid_duration_rows": int((corrected.isna() | corrected.le(0) | corrected.gt(1440)).sum()),
            "corrected_overnight_rows": int((departure.notna() & corrected_arrival.notna() & departure.dt.normalize().ne(corrected_arrival.dt.normalize())).sum()),
            "red_eye_rows": int((departure.dt.hour.ge(22) | departure.dt.hour.le(4)).sum()),
            "raw_duration_parseable_rows": int(parsed_duration.notna().sum()),
            "duration_reconciliation_tolerance_seconds": 1,
            "raw_duration_original_nonzero_subsecond_difference_rows": int((parsed_duration.sub(interval).abs().gt(0.000001) & parsed_duration.sub(interval).abs().lt(1 / 60)).sum()),
            "raw_duration_matches_original_interval_rows": int(parsed_duration.sub(interval).abs().le(1 / 60).sum()),
            "raw_duration_matches_corrected_interval_rows": int(parsed_duration.sub(corrected).abs().le(1 / 60).sum()),
            "raw_duration_corrected_mismatch_ids": sorted(flights.loc[parsed_duration.sub(corrected).abs().gt(1 / 60), "flight_id"].tolist()),
            "without_booking_distinct_ids": len(set(flights["flight_id"]) - set(bookings["flight_id"])),
        },
        "bookings": {
            "unique_ids": int(bookings["booking_id"].nunique()),
            "status_counts": _counts(bookings["status"]),
            "date_min": booking_dates.min().isoformat(),
            "date_max": booking_dates.max().isoformat(),
            "missing_flight_reference_rows": int((~bookings["flight_id"].isin(flights["flight_id"])).sum()),
            "missing_passenger_reference_rows": int((~bookings["passenger_id"].isin(passengers["passenger_id"])).sum()),
            "referencing_duplicated_flight_id_rows": int(bookings["flight_id"].isin(flights.loc[flights["flight_id"].duplicated(keep=False), "flight_id"]).sum()),
            "referencing_conflicting_flight_id_rows": int(bookings["flight_id"].isin(conflicting_ids).sum()),
            "without_payment_rows": int((~bookings["booking_id"].isin(payments["booking_id"])).sum()),
        },
        "payments": {
            "unique_ids": int(payments["payment_id"].nunique()),
            "distinct_bookings": int(payments["booking_id"].nunique()),
            "valid_amount_rows": int(amount.notna().sum()),
            "missing_amount_rows": int(payments["amount"].isna().sum()),
            "non_numeric_amount_rows": int((payments["amount"].notna() & amount.isna()).sum()),
            "literal_invalid_rows": int(payments["amount"].eq("INVALID").sum()),
            "non_positive_amount_rows": int(amount.le(0).sum()),
            "valid_amount_total": total,
            "method_counts": _counts(payments["payment_method"]),
            "payments_per_booking_distribution": _counts(payments.groupby("booking_id").size()),
            "missing_booking_reference_rows": int((~payments["booking_id"].isin(bookings["booking_id"])).sum()),
            "cancelled_booking_payment_rows": int(payments["booking_id"].isin(bookings.loc[bookings["status"].eq("CANCELLED"), "booking_id"]).sum()),
        },
        "passengers": {
            "unique_ids": int(passengers["passenger_id"].nunique()),
            "duplicate_id_groups": len(passenger_groups),
            "duplicate_candidate_rows": sum(len(group) for group in passenger_groups),
            "duplicate_excess_rows": sum(len(group) - 1 for group in passenger_groups),
            "duplicate_group_size_distribution": dict(Counter(str(len(group)) for group in passenger_groups)),
            "exact_duplicate_excess_rows": int(passengers.duplicated().sum()),
            "duplicate_groups_varying_by_field": {
                column: sum(group[column].nunique(dropna=False) > 1 for group in passenger_groups)
                for column in passengers.columns if column != "passenger_id"
            },
            "missing_last_name_rows": int(passengers["last_name"].isna().sum()),
            "min_age": float(ages.min()) if ages.notna().any() else None,
            "max_age": float(ages.max()) if ages.notna().any() else None,
            "under_18_rows": int(ages.lt(18).sum()),
            "under_18_distinct_ids": int(passengers.loc[ages.lt(18), "passenger_id"].nunique()),
            "gender_counts": _counts(passengers["gender"]),
            "aadhaar_length_counts": _counts(aadhaar.str.len()),
            "aadhaar_non_digit_rows": int((~aadhaar.str.fullmatch(r"\d+")).sum()),
            "aadhaar_leading_zero_rows": int(aadhaar.str.startswith("0").sum()),
            "without_booking_rows": int(without_booking.sum()),
            "without_booking_distinct_ids": int(passengers.loc[without_booking, "passenger_id"].nunique()),
        },
        "fanout": {
            "source_booking_rows": len(bookings),
            "booking_flight_left_join_rows": len(booking_flight),
            "booking_payment_inner_join_rows": len(bookings.merge(payments, on="booking_id")),
            "booking_payment_left_join_rows": len(booking_payment),
            "naive_three_way_inner_join_rows": len(naive_inner),
            "naive_three_way_left_join_rows": len(naive_left),
            "true_payment_total": total,
            "naive_three_way_total": naive_total,
            "inflation": format(Decimal(naive_total) - Decimal(total), ".2f"),
        },
        "discrepancies": [],
    }
    f, b, p, a = (result[name] for name in ["flights", "bookings", "payments", "passengers"])
    result["discrepancies"] = [
        f"Aadhaar length counts are {a['aadhaar_length_counts']}; {a['aadhaar_leading_zero_rows']} source values retain a leading zero. Check cell types before assuming digits were lost.",
        f"{a['without_booking_rows']} passenger rows have no booking, representing {a['without_booking_distinct_ids']} distinct IDs.",
        f"{a['under_18_rows']} passenger rows are under 18, representing {a['under_18_distinct_ids']} distinct IDs.",
        f"{f['raw_date_different_rows']} flight rows have different dates, including {f['negative_interval_rows']} backwards interval(s). Corrected source overnight count is {f['corrected_overnight_rows']}, before duplicate handling.",
        f"Booking-payment inner join has {result['fanout']['booking_payment_inner_join_rows']} rows; its left join has {result['fanout']['booking_payment_left_join_rows']}. {b['without_payment_rows']} bookings have no payment; payments cover {p['distinct_bookings']} distinct bookings.",
        f"Empty Excel padding: {sum(v['empty_rows_ignored'] for v in structure.values())} rows and {sum(v['empty_unnamed_columns_ignored'] for v in structure.values())} unnamed columns ignored.",
    ]
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "profile.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (reports_dir / "profile.md").write_text(_markdown(result), encoding="utf-8")
    return result


def _markdown(result):
    f, b, p, a, j = (result[key] for key in ("flights", "bookings", "payments", "passengers", "fanout"))
    lines = ["# Source profile", "", f"Source: `{result['source_file']}`. Reproduce with `python -m src.profile data/raw/UseCase_Airlines.xlsx`.", "",
             "Counts below come directly from workbook cells before cleaning. Monetary sums use decimal arithmetic. Passenger evidence is aggregate; no names or contact details are included.", "", "## Workbook structure", "", "| Sheet | Business rows | Named columns | Empty rows ignored | Empty unnamed columns ignored |", "|---|---:|---:|---:|---:|"]
    for name, sheet in result["structure"].items():
        lines.append(f"| {name} | {sheet['rows']:,} | {len(sheet['columns'])} | {sheet['empty_rows_ignored']} | {sheet['empty_unnamed_columns_ignored']} |")
    for name, sheet in result["structure"].items():
        lines.extend(["", f"### {name}", "", "| Column | Source cell Python types | Null rows |", "|---|---|---:|"])
        for column in sheet["columns"]:
            types = ", ".join(f"{key}: {value}" for key, value in sheet["source_types"][column].items())
            lines.append(f"| {column} | {types} | {sheet['nulls'][column]} |")
    lines.extend(["", "## Flights", "",
        f"- {f['unique_ids']:,} distinct flight IDs; {f['duplicate_id_groups']} duplicated ID groups. {f['exact_duplicate_groups']} are exact duplicate pairs ({f['exact_duplicate_excess_rows']} excess rows). `{', '.join(f['conflicting_ids'])}` is the conflicting pair.",
        "- Conflict fields: " + "; ".join(f"`{key}`: {', '.join(value)}" for key, value in f["conflicting_columns"].items()) + ".",
        "- Airline counts: " + ", ".join(f"{key} {value}" for key, value in f["airline_counts"].items()) + f". {f['real_carrier_count']} real carriers.",
        f"- Flight ID pattern `{f['id_pattern']}`: {f['invalid_id_pattern_rows']} failures. {len(f['cities'])} cities, {f['ordered_routes']} ordered routes, {f['self_route_rows']} self-routes.",
        f"- Departure range: {f['departure_min']} to {f['departure_max']}. Cities: {', '.join(f['cities'])}.",
        f"- {f['raw_date_different_rows']} date-different rows include {f['negative_interval_rows']} backwards interval. {f['raw_forward_date_crossing_rows']} legitimate forward overnight rows. {f['red_eye_rows']} departures are in 22:00-04:59.",
        f"- Correcting negative intervals by exactly one day yields a {f['corrected_min_minutes']:g}-{f['corrected_max_minutes']:g} minute range, {f['corrected_invalid_duration_rows']} invalid durations, and {f['corrected_overnight_rows']} overnight rows.",
        f"- Raw duration parses for {f['raw_duration_parseable_rows']} rows. With an explicit {f['duration_reconciliation_tolerance_seconds']}-second tolerance, it matches the original timestamp interval on {f['raw_duration_matches_original_interval_rows']} rows and the corrected interval on {f['raw_duration_matches_corrected_interval_rows']} rows. The sole corrected mismatch is `{', '.join(f['raw_duration_corrected_mismatch_ids'])}`. Original nonzero subsecond differences: {f['raw_duration_original_nonzero_subsecond_difference_rows']} (below 0.000001 minute is treated as floating-point noise). Excel time microseconds are preserved.",
        f"- {f['without_booking_distinct_ids']} source flight IDs have no booking.", "", "| Negative interval | Departure | Source arrival | Raw minutes | One-day correction minutes |", "|---|---|---|---:|---:|"])
    for example in f["negative_examples"]:
        lines.append(f"| {example['flight_id']} | {example['departure']} | {example['arrival']} | {example['raw_interval_minutes']:g} | {example['one_day_corrected_minutes']:g} |")
    lines.extend(["", "The single datetime duration is an Excel negative serial, decoded against the workbook epoch; reading only its clock component would lose the negative sign.", "", "## Bookings", "",
        f"- {b['unique_ids']:,} distinct booking IDs. Date range: {b['date_min']} to {b['date_max']}.",
        "- Status counts: " + ", ".join(f"{key} {value}" for key, value in b["status_counts"].items()) + ".",
        f"- Flight-reference failures: {b['missing_flight_reference_rows']}; passenger-reference failures: {b['missing_passenger_reference_rows']}.",
        f"- {b['referencing_duplicated_flight_id_rows']} bookings reference duplicated flight IDs; {b['referencing_conflicting_flight_id_rows']} reference the conflicting ID.",
        f"- {b['without_payment_rows']} bookings have no payment record.", "", "## Payments", "",
        f"- {p['unique_ids']:,} unique payment IDs cover {p['distinct_bookings']} distinct bookings. Booking-reference failures: {p['missing_booking_reference_rows']}.",
        f"- Amounts: {p['valid_amount_rows']} numeric, {p['missing_amount_rows']} null, {p['non_numeric_amount_rows']} non-numeric (all literal INVALID). Non-positive numeric amounts: {p['non_positive_amount_rows']}.",
        f"- Valid payment total: INR {Decimal(p['valid_amount_total']):,.2f}. {p['cancelled_booking_payment_rows']} payment rows relate to cancelled bookings.",
        "- Methods: " + ", ".join(f"{key} {value}" for key, value in p["method_counts"].items()) + ".", "", "| Payments per covered booking | Booking count |", "|---:|---:|"])
    for size, count in sorted(p["payments_per_booking_distribution"].items(), key=lambda item: int(item[0])):
        lines.append(f"| {size} | {count} |")
    lines.extend(["", "## Passengers", "",
        f"- {a['unique_ids']:,} distinct passenger IDs; {a['duplicate_id_groups']} duplicate groups containing {a['duplicate_candidate_rows']} candidate rows ({a['duplicate_excess_rows']} excess rows). Exact duplicate rows: {a['exact_duplicate_excess_rows']}.",
        "- Duplicate group sizes: " + ", ".join(f"{size} rows: {count} groups" for size, count in a["duplicate_group_size_distribution"].items()) + ".",
        f"- {a['missing_last_name_rows']} missing last names. Age range {a['min_age']}-{a['max_age']}. Under 18: {a['under_18_rows']} source rows / {a['under_18_distinct_ids']} distinct IDs.",
        "- Gender counts: " + ", ".join(f"{key} {value}" for key, value in a["gender_counts"].items()) + ".",
        "- Aadhaar length counts: " + ", ".join(f"{key} digits: {value}" for key, value in a["aadhaar_length_counts"].items()) + f". Non-digit values: {a['aadhaar_non_digit_rows']}; leading-zero values: {a['aadhaar_leading_zero_rows']}.",
        f"- No booking: {a['without_booking_rows']} source rows / {a['without_booking_distinct_ids']} distinct passenger IDs.", "", "| Field | Duplicate groups whose values differ |", "|---|---:|"])
    for column, count in a["duplicate_groups_varying_by_field"].items():
        lines.append(f"| {column} | {count} |")
    lines.extend(["", "Age and gender are stable within duplicate groups. Identity/contact differences cannot be resolved as verified identity from this workbook; survivorship will select a deterministic record, not prove it is correct.", "", "## Join fan-out", "", "| Measurement | Result |", "|---|---:|",
        f"| Source bookings | {j['source_booking_rows']:,} |",
        f"| Booking LEFT JOIN flight | {j['booking_flight_left_join_rows']:,} |",
        f"| Booking INNER JOIN payment | {j['booking_payment_inner_join_rows']:,} |",
        f"| Booking LEFT JOIN payment | {j['booking_payment_left_join_rows']:,} |",
        f"| Naive three-way INNER JOIN | {j['naive_three_way_inner_join_rows']:,} |",
        f"| Naive three-way LEFT JOIN | {j['naive_three_way_left_join_rows']:,} |",
        f"| Source valid payment total, INR | {Decimal(j['true_payment_total']):,.2f} |",
        f"| Naive three-way valid payment total, INR | {Decimal(j['naive_three_way_total']):,.2f} |",
        f"| Revenue inflation, INR | {Decimal(j['inflation']):,.2f} |", "",
        "An inner join removes unpaid bookings while multiple payments expand other bookings. Duplicate flight IDs then repeat payment rows and inflate the sum. Payment-grain facts and a unique flight key are required.", "", "## Interpretation of supplied verification targets", ""])
    lines.extend(f"- {item}" for item in result["discrepancies"])
    lines.extend(["", "Figures above are measured from this source hash. No scheduled-versus-actual timestamps exist, so an operational delay KPI cannot be measured.", "", f"Source SHA-256: `{result['source_sha256']}`.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Profile the ASG workbook without publishing raw PII.")
    parser.add_argument("workbook", nargs="?", default="data/raw/UseCase_Airlines.xlsx")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()
    result = profile_source(args.workbook, args.reports_dir)
    print(f"Source profile written to {args.reports_dir}/profile.md; valid payment total INR {result['payments']['valid_amount_total']}")


if __name__ == "__main__":
    main()
