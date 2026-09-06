# Power BI verification

The report was built and refreshed in Power BI Desktop against the gold exports. `ASG_Airlines.pbix` contains a cached model, so it opens with data without a refresh; refreshing requires setting the `SourceFolder` parameter to a local `data/gold` path.

## Model

| Item | Value |
|---|---|
| Tables | 12 (9 backed by gold CSVs, 2 date role-playing references, 1 measure table) |
| Measures | 26, held in `_Measures` |
| Relationships | 8, all active, many-to-one, single cross-filter direction |
| Pages | Executive Overview, Duration & Schedule, Route & Airline Performance, Data Quality & Anomalies |
| Visuals | 32 |

`dq_issue_summary` is intentionally disconnected; it is an audit register, not a fact.

`fact_payment` joins `fact_booking`, and `fact_booking` joins `fact_flight`. Payments never join flights directly, so payment measures cannot fan out across the duplicated flight keys present in the source.

## Refresh

All 12 tables load without error. Row counts on refresh:

| Table | Rows |
|---|---|
| dim_airline | 5 |
| dim_date / dim_departure_date / dim_booking_date | 371 |
| dim_route | 31 |
| dim_passenger | 1,001 |
| dim_status | 5 |
| fact_flight | 1,004 (1,003 real + 1 unknown member) |
| fact_booking | 1,000 |
| fact_payment | 1,000 |
| dq_issue_summary | 15 |

## Figures rendered in the report

Each was compared against the corresponding gold CSV.

| Measure | Rendered | Source |
|---|---|---|
| Flights | 1,003 | `fact_flight`, excluding the unknown member |
| Bookings | 1,000 | `fact_booking` |
| Average Duration Minutes | 164.67 | `fact_flight.duration_minutes` |
| Gross Valid Payment Amount | 7,385,142.98 | `fact_payment`, `amount_quality = valid` |
| Cancellation Rate | 31.4% | 314 of 1,000 bookings |
| Payment Coverage | 63.7% | 637 of 1,000 bookings carry a payment |
| Overnight Share | 12.2% (122) | departure date differs from arrival date |
| Red Eye Share | 27.0% (271) | departure hour 22–04 |
| Source Issue Events | 714 | `dq_issue_summary`, 15 categories |
| Corrected Flights | 1 | SJ192 |

The 714 issue events overlap by design — one booking can be both unpaid and missing a status — so the figure counts events, not distinct rows.

## Known limitations

Operational delay is not computable. The source carries only actual departure and arrival timestamps; on-time performance would require scheduled values. The Data Quality page states this and reports anomaly counts in place of a delay metric.

The `UNKNOWN` member on the `year_month` axis is filtered out of the booking trend visuals — it is the unknown-date placeholder and carries no bookings. The `UNKNOWN` airline category is retained: it represents 67 real flights whose carrier was missing or held a sentinel value in the source, and removing it would break the flight total.
