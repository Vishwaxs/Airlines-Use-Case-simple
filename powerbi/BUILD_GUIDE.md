# Power BI build guide

Status: The CSVs, measures and PBIP project are available. The semantic model queries and types have been structurally aligned to the gold CSV exports as documented in `VERIFICATION.md`. The PBIX, visual rendering, DAX execution and screenshots require Power BI Desktop verification. Save the finished report as `powerbi/ASG_Airlines.pbix` and genuine screenshots in `powerbi/screenshots/`.

## Load one successful run

Use `data/gold/` under the output root whose `reports/run_manifest.json` has `status = 'success'`. Import the following CSVs using UTF-8, a comma delimiter, and their headers:

`dim_date`, `dim_airline`, `dim_route`, `dim_passenger`, `dim_status`, `fact_flight`, `fact_booking`, `fact_payment`, and `dq_issue_summary`.

Name queries exactly as the filenames without `.csv`. Create two reference queries from `dim_date`: `dim_departure_date` and `dim_booking_date`. Disable load for the base `dim_date` query. The parameter `SourceFolder` configures the local directory containing the gold CSVs; on first open, set it to the absolute path of your `data/gold/` folder. All queries read local files via `File.Contents`.

Do not import raw, bronze, silver, quarantine, or passenger-survivorship data. Importing `kpi_*.csv` is optional for reconciliation; keep each such table disconnected and label it as an unfiltered run snapshot. Do not combine preaggregated KPI rows with facts or create relationships from KPI tables.

`kpi_booking_month.csv` supplies the expected booking/payment trend for 13 year-month periods, April 2025 through April 2026. Build interactive trends from `dim_booking_date.year_month` and the booking/payment measures, then reconcile them to this extract with filters cleared. Do not combine both Aprils into one month-of-year value. The historical Azure records cover 13 CSVs and predate this fourteenth export.

Remove guessed type-conversion steps and set these types explicitly. Use English (United States) to parse the machine-formatted CSV decimal point and ISO-style timestamps; apply INR display formatting afterward.

| Columns | Power Query/model type |
| --- | --- |
| Every `*_sk`; age; year/month/day/weekday; departure_hour; affected_rows | Whole number; retain nulls |
| `flight_id`, `booking_id`, `payment_id`, `passenger_token`; categorical labels and reasons | Text; never infer identifiers as numbers |
| `date` in each date query | Date; keep the unknown row's date blank |
| `departure_time`, `arrival_time` | Duplicate each as `*_source_text` while still Text; convert the original columns to Date/Time without truncating fractional seconds |
| `duration_minutes` | Decimal number; display two decimals, retain stored precision |
| `amount` | Fixed decimal number; display INR with two decimals; blanks stay blank |
| `is_unknown`, `is_valid`, `is_unknown_member`, `is_overnight`, `is_red_eye`, `was_corrected`, `duration_matches_raw`, `has_unresolved_flight`, `has_unresolved_passenger` where present | True/False; retain nulls where allowed |

Use the exported `duration_minutes` for measures. Power BI's model stores Date/Time at roughly 3.33 ms precision; the duplicate text retains the exact exported fraction for reconciliation. Do not calculate duration again from rounded model timestamps. [Power BI data types](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-data-types).

Disable automatic relationship detection and Auto date/time for this report. Keep the date role tables as ordinary dimensions; their unknown date row is blank and these measures do not need date-table time-intelligence functions. Sort year-month labels chronologically. Hide technical keys and passenger tokens from Report view; hiding columns is not an access-control boundary.

## Create these relationships only

Every relationship is active, one-to-many, with **Single** cross-filter direction from the left table to the right table.

| One side | Many side |
| --- | --- |
| `dim_airline.airline_sk` | `fact_flight.airline_sk` |
| `dim_route.route_sk` | `fact_flight.route_sk` |
| `dim_departure_date.date_sk` | `fact_flight.departure_date_sk` |
| `fact_flight.flight_sk` | `fact_booking.flight_sk` |
| `dim_booking_date.date_sk` | `fact_booking.booking_date_sk` |
| `dim_passenger.passenger_sk` | `fact_booking.passenger_sk` |
| `dim_status.status_sk` | `fact_booking.status_sk` |
| `fact_booking.booking_sk` | `fact_payment.booking_sk` |

This is a fact chain: one flight can have many bookings and one booking can have many payments. Payment measures sum `fact_payment.amount` directly. Do not flatten the chain into repeated flight/booking/payment rows.

The two date roles avoid a second active path from one calendar into bookings. Airline, route, and departure-date filters reach all three facts; booking-date, passenger, and status filters reach bookings/payments only. There is no relationship between the two date tables, no direct flight-to-payment relationship, and no bidirectional relationship. [Microsoft guidance on date roles](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema).

Retain surrogate key -1 rows. The unknown-flight placeholder carries unresolved bookings/payments; the `[Flights]` measure excludes it. Actual flights with UNKNOWN airline still count. Do not apply `fact_flight.is_unknown_member = false` as a global/page filter: that would also discard unresolved bookings and their payments through the fact chain. A departure-date range excludes undated unknown-flight bookings; label and test that behavior.

Keep `dq_issue_summary` disconnected. Its fields support a static issue breakdown for the selected source run; airline, route, and booking slicers must not imply that these source counts were recalculated.

## Add measures and pages

Create each definition from `measures.dax` as a separate measure. Use whole-number formatting for counts, `0.00` for minutes, `0.0%` for rates/shares, and INR with two decimals for amounts. Display missing amounts as blank or an em dash, never as a known zero. See `docs/KPI_DEFINITIONS.md` for denominators.

Use a 16:9 canvas, a light background, dark text, one blue accent, and amber for quality issues. Keep titles factual, units visible, and the same navigation and spacing on all four pages. Avoid gauges, maps, decorative icons, and repetitive cards.

| Page | Contents | Filters and interpretation |
| --- | --- | --- |
| Executive Overview | Cards: Flights, Average Duration Minutes, Bookings, Gross Valid Payment Amount, Cancellation Rate, Payment Coverage. Airline flight-count bar; booking-month line with Bookings and a separately scaled payment chart. | Airline and route slicers. Label the trend “Bookings by booking month”; payments on that axis are associated payments, not a cash-date trend. Default to all dates for the reconciliation view. |
| Duration & Schedule | Average duration, overnight share, red-eye share; departures by hour; route matrix with average and population spread; detail table for corrected flights using flight ID, timestamps, duration, and correction reason. | Departure-date, airline, route slicers. Keep red-eye and overnight as distinct categories. A corrected duration does not demonstrate a delay. |
| Route & Airline Performance | Ordered-route bars by Flights; airline flight count/share; route matrix with Flights, Bookings, Gross Valid Payment Amount, and average duration. | Departure-date, airline, route slicers. Keep UNKNOWN visible where it carries bookings/payments. An airline selection does not rescale airline shares to 100%. |
| Data Quality & Anomalies | Source Issue Events card; issue bar and table using table_name, issue, treatment, affected_rows. Separate operational cards for Corrected Flights, Unresolved Flight Bookings, Missing Amount Payments, Invalid Amount Payments. | Only table_name/issue slicers for the disconnected source summary. Label it “Source run issue events; a row can have several issues.” The operational cards are a separate section. State “Operational delay unavailable: scheduled and actual timestamps are not supplied.” |

Booking-date or status slicers may be added to a clearly labeled bookings/payments section on the overview. Set their interactions to None for flight-only visuals and explain that they do not select flights. A status selection changes the booking cohort: CANCELLED alone gives a 100% cancellation rate. Do not add payment-method/amount-quality slicers to coverage or no-payment cards; those cards describe the presence of any payment record.

## Verify before submission

1. With all filters cleared, match every summary KPI to `kpi_summary.csv`. Compare route and airline tables to `kpi_route.csv` and `kpi_airline.csv`. Compare money to the cent and minutes to the displayed precision.
2. Confirm the flight card excludes exactly the unknown placeholder while booking/payment totals include unresolved-flight rows. Select UNKNOWN airline and verify actual unknown-airline flights remain visible.
3. Select a route, airline, and departure date; reconcile resulting payment sums by following the single relationship path. Select a booking month and verify only booking/payment visuals change.
4. Check a booking with multiple valid payments: all amounts contribute, but the average-payment denominator counts that booking once. Check a booking with only invalid/missing payments: it counts toward coverage, not toward the valid-paid-booking denominator.
5. Inspect SJ192's corrected interval and a legitimate overnight flight. Verify the displayed duration uses the exported number and fractional timestamp text is retained.
6. Check CANCELLED and CONFIRMED status selections, an empty selection, and a route/date with no valid payments. No-data ratios/amounts should be blank, and no DAX visual should show an error.
7. Verify operational slicers do not change the disconnected source issue summary. Do not label overlapping event counts as unique rows or delayed flights.
8. Save, close, and reopen `ASG_Airlines.pbix`; refresh from the documented source. Capture each page and the relationship model from the working report. Record the source run ID, expected/observed KPI checks, and any failure in `powerbi/VERIFICATION.md`.

These checks were run in Power BI Desktop against the refreshed model; results are recorded in `VERIFICATION.md`.

The current local baseline has 714 source issue events, 1,000 bookings across 13 year-month periods, 637 bookings with any payment record, and 606 with a valid payment amount. Use 606 for the average-valid-payment denominator.
