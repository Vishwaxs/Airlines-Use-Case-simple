# Assumptions that affect interpretation

| Assumption | Reason and effect |
|---|---|
| A negative flight interval means arrival should move forward by one calendar day. | SJ192 is the observed example: -1,140 becomes 300 minutes. Only negative intervals are changed; a result at or below zero, or above 1,440 minutes, is quarantined. |
| Timestamps share one unspecified local time basis. | The workbook provides no timezone fields. No timezone conversion or scheduled-versus-actual comparison is possible. |
| Raw duration is a reconciliation field. | It uses mixed Excel time/datetime representations and repeats the erroneous SJ192 interval. Timestamps determine analytical duration. |
| Excel formula caches may be absent after another tool saves the workbook. | The source duration column contains 1,020 formulas. Ingestion reads their cached results; missing caches are flagged as unparseable raw duration while valid timestamps still determine duration. The pipeline does not recalculate or overwrite the source workbook. |
| Overnight means departure and corrected arrival fall on different dates. | Red-eye separately means departure at 22:00-04:59. The two flags answer different questions. |
| Each flight ID should identify one flight record. | Exact copies can collapse; conflicting copies cannot safely select a schedule. Their bookings retain an unknown flight reference. |
| Passenger ID is the source grouping key. | Duplicate identities conflict without update timestamps. Completeness, 12-digit Aadhaar shape, email ordering, then source-row order choose a repeatable survivor; this does not verify identity. |
| Age is used as supplied, after range checks. | Date of birth is sensitive and not needed downstream; the source provides no authoritative age reference date. |
| Missing and sentinel values represent different source problems. | Both remain visible in quality reporting even where their analytical label is UNKNOWN. INVALID booking status remains INVALID. |
| Incomplete amounts do not equal zero. | Missing/non-numeric amounts remain null, and their payment records remain available for coverage analysis. |
| Gross valid payment amount is the sum of valid numeric payments across every booking status. | No refunds, settlement status, currency column, or payment timestamp is available. The case uses INR; the result is not net recognised revenue. |
| Confirmed-booking payment amount filters the current booking status to CONFIRMED. | It is not revenue recognised on a travel date or a historical status snapshot. |
| Cancellation and confirmation rates use all retained bookings as the denominator. | UNKNOWN and INVALID statuses therefore reduce the rates; they are not silently excluded. |
| Payment coverage counts bookings with any payment record. | A payment with an unusable amount still proves a payment record exists. |
| Average valid payment per paid booking divides valid amount by distinct bookings with at least one valid amount. | Multiple payments are combined at booking level. It is a payment-based ticket-value proxy, not a listed fare. |
| Route traffic reports both flight and booking counts. | A booking is not proof that a passenger boarded. There is no capacity, check-in or flown-status data. |
| True operational delay is unavailable. | Scheduled and actual timestamps are not separate. Duration corrections and other anomalies are reported instead. |

Source differences worth retaining: 382 passenger rows without bookings represent 364 distinct IDs; 227 minor rows represent 215 distinct IDs. All 1,039 Aadhaar values already have 12 digits, including 114 with a leading zero. Normalization is still tested against shortened synthetic input.

This is a full-refresh, single-workbook implementation. Reproducibility means identical analytical tables for the same input and pepper; run IDs, timestamps and timings are intentionally different.
