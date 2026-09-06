# KPI definitions

SQL definitions are in `sql/03_kpi_views.sql`; the monthly export query is in `src/kpi.py`. Power BI measures are in `powerbi/measures.dax`. The exported `kpi_*.csv` files describe the complete successful run. The DAX definitions specify filter-dependent calculations; their execution in Power BI remains unverified.

| KPI | Definition and interpretation |
| --- | --- |
| Flight count | Rows in `fact_flight` excluding `is_unknown_member = true`. Each retained flight ID counts once. Actual flights whose airline is UNKNOWN still count. |
| Average duration | Mean of exported `duration_minutes` across retained flights. Use the corrected timestamp interval; do not average raw duration values or average route averages. |
| Route traffic | Retained flight count by ordered source/destination. A-B and B-A are separate routes. Booking and payment counts are separate measures, not flight traffic. |
| Route duration spread | Population standard deviation of retained flight durations on the route. One flight gives zero; no flights gives blank. This describes variation, not delay. |
| Overnight share | Flights whose corrected arrival date is after departure date / retained flights. A legitimate next-day arrival is not itself a correction. |
| Red-eye share | Flights departing from 22:00 inclusive through 05:00 exclusive / retained flights. Overnight and red-eye flags can overlap but describe different facts. |
| Airline distribution | Retained flight count by airline. Airline share divides by all airlines in the same departure-date/route context; the DAX denominator removes airline filters. An airline slicer can therefore show shares totaling less than 100%. |
| Booking count | One row per retained booking, including bookings assigned to the unknown-flight member. |
| Payment count | One row per payment record, including invalid and missing amounts. Multiple payments for one booking remain separate. |
| Gross valid payment amount | Sum of amounts with `amount_quality = 'valid'`, at payment grain, across all booking statuses. It includes payments attached to cancelled bookings. It is not recognized revenue, net revenue, or profit. |
| Confirmed-booking payment amount | Valid payment amount for bookings whose status is CONFIRMED. Other status selections intersect this filter. |
| Cancellation rate | CANCELLED bookings / all bookings in the current booking cohort. With no filters, the denominator includes CONFIRMED, CANCELLED, PENDING, UNKNOWN, and INVALID statuses. |
| Confirmation rate | CONFIRMED bookings / the same booking denominator. |
| Payment coverage | Distinct bookings with any payment record / bookings. An invalid or missing amount still demonstrates a payment record, not a known amount paid. |
| Average valid payment per paid booking | Gross valid payment amount / distinct bookings with at least one valid payment. Bookings with only missing/invalid amounts are excluded from this denominator. Multiple valid payments for a booking contribute once to the denominator and all valid amounts to the numerator. |
| Bookings without payment | Bookings absent from `fact_payment`; this does not mean bookings whose payment amount is missing. |
| Corrected flights | Retained flights with `was_corrected = true`. This is a repair count, not a delayed-flight count. |
| Unresolved-flight bookings | Bookings with `has_unresolved_flight = true`; retained against flight key -1 so booking/payment totals remain available. |
| Missing/invalid amount payments | Missing counts `amount_quality = 'missing'`; the DAX invalid filter includes `non_numeric` and `out_of_range`. Validation quarantines out-of-range payments before gold, so those records appear in source issue reporting, not in final payment facts. Missing/non-numeric amounts remain null. |
| Source issue events | Sum of `dq_issue_summary.affected_rows`: 714 in this source run. One source row can have several issues, so events are not distinct affected records and cannot be divided by total rows to claim a defect rate. |
| Booking-month extract | `kpi_booking_month.csv` groups bookings by booking-date year and month, after aggregating valid payments per booking. It exports 13 periods from 2025-04 through 2026-04, totaling 1,000 bookings. Confirmed amounts use current CONFIRMED booking status. |

Flight measures respond to airline, route, and departure-date filters. Booking and payment measures also respond to booking-date, passenger, and status filters through the directed relationships. Booking filters do not travel back to flights. Payment filters do not travel back to bookings. The build guide keeps these controls scoped to the relevant visuals.

Cancellation and confirmation rates describe the selected cohort: selecting only CANCELLED yields 100% cancellation. Clearing status filters restores the all-status denominator. Fixed filters in the supplied measures use `KEEPFILTERS`, so a conflicting user selection produces an empty intersection. [DAX filter behavior](https://learn.microsoft.com/en-us/dax/keepfilters-function-dax).

No payment timestamp exists. A payment amount plotted by booking month means payments associated with bookings made in that month, not cash collected during that month. Flights cover a short departure-date window; a booking-month trend is not an airline operations trend. The complete run has 637 bookings with any payment record and 606 with at least one valid amount; only the latter count is the denominator for average valid payment per paid booking.

The source has no scheduled-versus-actual timestamp pair, cancellation fee, refund, seat capacity, or passenger boarding count. Delay, on-time performance, net revenue, load factor, and passengers carried cannot be calculated. The anomaly page reports measured quality issues and corrections instead. Ratios with no denominator and amounts with no valid observations remain blank; count measures return zero.
