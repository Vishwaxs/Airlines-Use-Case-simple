# Data quality report

Issue counts are source-row events. A row can have several issues; do not add these counts to estimate unique bad records.

| Table | Source rows | Silver rows | Quarantined rows |
|---|---:|---:|---:|
| flights | 1020 | 1003 | 2 |
| payments | 1000 | 1000 | 0 |
| bookings | 1000 | 1000 | 0 |
| passengers | 1039 | 1000 | 0 |

| Table | Issue | Affected rows | Treatment |
|---|---|---:|---|
| bookings | booking_without_payment | 363 | retain |
| bookings | missing_status | 45 | retain_as_unknown |
| bookings | sentinel_status | 30 | retain_as_invalid |
| bookings | unavailable_flight_reference | 2 | retain_with_unknown_flight |
| flights | conflicting_duplicate_key | 2 | quarantine |
| flights | duration_reconciliation_mismatch | 1 | retain_timestamp_duration |
| flights | exact_duplicate | 15 | exact_duplicate_removed |
| flights | flight_without_booking | 20 | retain |
| flights | missing_airline | 41 | retain_as_unknown |
| flights | negative_duration | 1 | roll_arrival_forward_one_day |
| flights | sentinel_airline | 31 | retain_as_unknown |
| passengers | duplicate_passenger_id | 75 | deterministic_survivorship |
| passengers | missing_last_name | 10 | mask_available_name |
| payments | missing_amount | 48 | retain_with_null_amount |
| payments | non_numeric_amount | 30 | retain_with_null_amount |

## Final results

- 1003 real flights; 1 timestamp correction(s).
- 122 overnight flights and 271 red-eye departures after duplicate treatment.
- Raw duration reconciliation: 1002 matches, 1 mismatches, 0 unparseable values among retained flights.
- 15 exact flight copies removed; 2 conflicting-key rows quarantined; 2 bookings flagged for an unknown flight reference.
- Passenger survivorship retained 1000 IDs from 1039 rows. Duplicate candidates and ranking are recorded in passenger_survivorship.csv.
- Gross valid payment amount: INR 7,385,142.98. Missing and non-numeric amounts remain NULL.
- Independent source fan-out check: INR 7,385,142.98 becomes INR 7,593,758.92 in the naive three-way join, a difference of INR 208,615.94.
- Silver and analytical payment totals reconcile exactly in the model checks. Payment facts retain a single row per payment_id. Quarantined amounts are excluded from the analytical total.
- Delay minutes cannot be calculated: the source has no scheduled-versus-actual timestamps.
- kpi_booking_month.csv: 13 actual year-month periods, grouped by booking date; payments are associated with booking month, not a payment transaction date.

Timestamp durations retain microseconds. Raw-duration reconciliation uses a one-second tolerance; the source report records any smaller differences.
- SJ192: raw duration -1140 minutes; repaired duration 300 minutes; overnight = False.
