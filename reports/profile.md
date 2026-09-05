# Source profile

Source: `UseCase_Airlines.xlsx`. Reproduce with `python -m src.profile data/raw/UseCase_Airlines.xlsx`.

Counts below come directly from workbook cells before cleaning. Monetary sums use decimal arithmetic. Passenger evidence is aggregate; no names or contact details are included.

## Workbook structure

| Sheet | Business rows | Named columns | Empty rows ignored | Empty unnamed columns ignored |
|---|---:|---:|---:|---:|
| flights | 1,020 | 7 | 0 | 4 |
| payments | 1,000 | 4 | 0 | 0 |
| bookings | 1,000 | 9 | 12 | 0 |
| passengers | 1,039 | 9 | 0 | 0 |

### flights

| Column | Source cell Python types | Null rows |
|---|---|---:|
| flight_id | str: 1020 | 0 |
| airline | str: 979, NoneType: 41 | 41 |
| source | str: 1020 | 0 |
| destination | str: 1020 | 0 |
| departure_time | datetime: 1020 | 0 |
| arrival_time | datetime: 1020 | 0 |
| duration | time: 1019, datetime: 1 | 0 |

### payments

| Column | Source cell Python types | Null rows |
|---|---|---:|
| payment_id | str: 1000 | 0 |
| booking_id | str: 1000 | 0 |
| amount | float: 913, NoneType: 48, str: 30, int: 9 | 48 |
| payment_method | str: 1000 | 0 |

### bookings

| Column | Source cell Python types | Null rows |
|---|---|---:|
| booking_id | str: 1000 | 0 |
| passenger_id | str: 1000 | 0 |
| flight_id | str: 1000 | 0 |
| booking_date | datetime: 1000 | 0 |
| status | str: 955, NoneType: 45 | 45 |
| passport_number | str: 1000 | 0 |
| seat_number | str: 1000 | 0 |
| emergency_contact_name | str: 1000 | 0 |
| emergency_contact_phone | str: 1000 | 0 |

### passengers

| Column | Source cell Python types | Null rows |
|---|---|---:|
| passenger_id | str: 1039 | 0 |
| first_name | str: 1039 | 0 |
| last_name | str: 1029, NoneType: 10 | 10 |
| age | int: 1039 | 0 |
| gender | str: 1039 | 0 |
| email | str: 1039 | 0 |
| phone | str: 1039 | 0 |
| aadhaar_id | str: 1039 | 0 |
| date_of_birth | datetime: 1039 | 0 |

## Flights

- 1,004 distinct flight IDs; 16 duplicated ID groups. 15 are exact duplicate pairs (15 excess rows). `6F250` is the conflicting pair.
- Conflict fields: `6F250`: source, departure_time, arrival_time, duration.
- Airline counts: IndiGo 249, SpiceJet 240, Air India 236, Vistara 223, <NULL> 41, UNKNOWN 31. 4 real carriers.
- Flight ID pattern `[A-Z0-9]{2}\d{3}`: 0 failures. 6 cities, 30 ordered routes, 0 self-routes.
- Departure range: 2026-04-17T12:25:41.701000 to 2026-04-20T23:38:41.701000. Cities: BLR, BOM, CCU, DEL, HYD, MAA.
- 125 date-different rows include 1 backwards interval. 124 legitimate forward overnight rows. 279 departures are in 22:00-04:59.
- Correcting negative intervals by exactly one day yields a 30-300 minute range, 0 invalid durations, and 124 overnight rows.
- Raw duration parses for 1020 rows. With an explicit 1-second tolerance, it matches the original timestamp interval on 1020 rows and the corrected interval on 1019 rows. The sole corrected mismatch is `SJ192`. Original nonzero subsecond differences: 0 (below 0.000001 minute is treated as floating-point noise). Excel time microseconds are preserved.
- 20 source flight IDs have no booking.

| Negative interval | Departure | Source arrival | Raw minutes | One-day correction minutes |
|---|---|---|---:|---:|
| SJ192 | 2026-04-19T18:45:42 | 2026-04-18T23:45:42 | -1140 | 300 |

The single datetime duration is an Excel negative serial, decoded against the workbook epoch; reading only its clock component would lose the negative sign.

## Bookings

- 1,000 distinct booking IDs. Date range: 2025-04-17T11:37:36.951000 to 2026-04-17T11:37:36.951000.
- Status counts: CONFIRMED 320, CANCELLED 314, PENDING 291, <NULL> 45, INVALID 30.
- Flight-reference failures: 0; passenger-reference failures: 0.
- 32 bookings reference duplicated flight IDs; 2 reference the conflicting ID.
- 363 bookings have no payment record.

## Payments

- 1,000 unique payment IDs cover 637 distinct bookings. Booking-reference failures: 0.
- Amounts: 922 numeric, 48 null, 30 non-numeric (all literal INVALID). Non-positive numeric amounts: 0.
- Valid payment total: INR 7,385,142.98. 306 payment rows relate to cancelled bookings.
- Methods: UPI 358, CARD 329, NETBANKING 313.

| Payments per covered booking | Booking count |
|---:|---:|
| 1 | 370 |
| 2 | 189 |
| 3 | 63 |
| 4 | 13 |
| 5 | 1 |
| 6 | 1 |

## Passengers

- 1,000 distinct passenger IDs; 36 duplicate groups containing 75 candidate rows (39 excess rows). Exact duplicate rows: 0.
- Duplicate group sizes: 2 rows: 33 groups, 3 rows: 3 groups.
- 10 missing last names. Age range 1.0-89.0. Under 18: 227 source rows / 215 distinct IDs.
- Gender counts: M 545, F 494.
- Aadhaar length counts: 12 digits: 1039. Non-digit values: 0; leading-zero values: 114.
- No booking: 382 source rows / 364 distinct passenger IDs.

| Field | Duplicate groups whose values differ |
|---|---:|
| first_name | 11 |
| last_name | 27 |
| age | 0 |
| gender | 0 |
| email | 36 |
| phone | 36 |
| aadhaar_id | 36 |
| date_of_birth | 36 |

Age and gender are stable within duplicate groups. Identity/contact differences cannot be resolved as verified identity from this workbook; survivorship will select a deterministic record, not prove it is correct.

## Join fan-out

| Measurement | Result |
|---|---:|
| Source bookings | 1,000 |
| Booking LEFT JOIN flight | 1,032 |
| Booking INNER JOIN payment | 1,000 |
| Booking LEFT JOIN payment | 1,363 |
| Naive three-way INNER JOIN | 1,028 |
| Naive three-way LEFT JOIN | 1,404 |
| Source valid payment total, INR | 7,385,142.98 |
| Naive three-way valid payment total, INR | 7,593,758.92 |
| Revenue inflation, INR | 208,615.94 |

An inner join removes unpaid bookings while multiple payments expand other bookings. Duplicate flight IDs then repeat payment rows and inflate the sum. Payment-grain facts and a unique flight key are required.

## Interpretation of supplied verification targets

- Aadhaar length counts are {'12': 1039}; 114 source values retain a leading zero. Check cell types before assuming digits were lost.
- 382 passenger rows have no booking, representing 364 distinct IDs.
- 227 passenger rows are under 18, representing 215 distinct IDs.
- 125 flight rows have different dates, including 1 backwards interval(s). Corrected source overnight count is 124, before duplicate handling.
- Booking-payment inner join has 1000 rows; its left join has 1363. 363 bookings have no payment; payments cover 637 distinct bookings.
- Empty Excel padding: 12 rows and 4 unnamed columns ignored.

Figures above are measured from this source hash. No scheduled-versus-actual timestamps exist, so an operational delay KPI cannot be measured.

Source SHA-256: `82549a897f4829d3e06cfb21b8b1f9100a10cba268ceb3c4597f71ee558a9db3`.
