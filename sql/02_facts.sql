CREATE TABLE fact_flight AS
SELECT row_number() OVER (ORDER BY f.flight_id) AS flight_sk, f.flight_id,
       a.airline_sk, r.route_sk,
       CAST(strftime(f.departure_time, '%Y%m%d') AS INTEGER) AS departure_date_sk,
       f.departure_time, f.arrival_time, f.duration_minutes,
       hour(f.departure_time) AS departure_hour,
       f.is_overnight, f.is_red_eye, f.was_corrected,
       f.correction_reason, f.duration_matches_raw, false AS is_unknown_member
FROM silver_flights f
JOIN dim_airline a ON a.airline = f.airline
JOIN dim_route r ON r.source = f.source AND r.destination = f.destination
UNION ALL SELECT -1, 'UNKNOWN', -1, -1, -1, NULL, NULL, NULL, NULL,
                 false, false, false, NULL, NULL, true;
ALTER TABLE fact_flight ADD PRIMARY KEY (flight_sk);
CREATE UNIQUE INDEX unique_flight_id ON fact_flight(flight_id);

CREATE TABLE fact_booking AS
SELECT row_number() OVER (ORDER BY b.booking_id) AS booking_sk, b.booking_id,
       COALESCE(p.passenger_sk, -1) AS passenger_sk,
       COALESCE(f.flight_sk, -1) AS flight_sk,
       CAST(strftime(b.booking_date, '%Y%m%d') AS INTEGER) AS booking_date_sk,
       s.status_sk, f.flight_sk IS NULL AS has_unresolved_flight,
       p.passenger_sk IS NULL AS has_unresolved_passenger
FROM silver_bookings b
LEFT JOIN passenger_lookup p ON p.passenger_id = b.passenger_id
LEFT JOIN fact_flight f ON f.flight_id = b.flight_id AND NOT f.is_unknown_member
JOIN dim_status s ON s.status = b.status;
ALTER TABLE fact_booking ADD PRIMARY KEY (booking_sk);
CREATE UNIQUE INDEX unique_booking_id ON fact_booking(booking_id);

CREATE TABLE fact_payment AS
SELECT row_number() OVER (ORDER BY p.payment_id) AS payment_sk, p.payment_id,
       b.booking_sk, CAST(p.amount_cents * 0.01 AS DECIMAL(18,2)) AS amount,
       p.amount_quality, p.payment_method
FROM silver_payments p
JOIN fact_booking b ON b.booking_id = p.booking_id;
ALTER TABLE fact_payment ADD PRIMARY KEY (payment_sk);
CREATE UNIQUE INDEX unique_payment_id ON fact_payment(payment_id);

CREATE TABLE dq_issue_summary AS
SELECT table_name, issue, treatment, COUNT(*) AS affected_rows
FROM silver_issues GROUP BY table_name, issue, treatment;
