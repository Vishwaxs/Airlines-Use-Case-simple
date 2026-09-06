CREATE VIEW kpi_summary AS
SELECT
    (SELECT count(*) FROM fact_flight WHERE NOT is_unknown_member) AS flight_count,
    (SELECT avg(duration_minutes) FROM fact_flight WHERE NOT is_unknown_member) AS avg_duration_minutes,
    (SELECT avg(CAST(is_overnight AS INTEGER)) FROM fact_flight WHERE NOT is_unknown_member) AS overnight_share,
    (SELECT avg(CAST(is_red_eye AS INTEGER)) FROM fact_flight WHERE NOT is_unknown_member) AS red_eye_share,
    (SELECT count(*) FROM fact_booking) AS booking_count,
    (SELECT count(*) FROM fact_payment) AS payment_count,
    (SELECT sum(amount) FROM fact_payment WHERE amount_quality = 'valid') AS gross_valid_payment_amount,
    (SELECT sum(p.amount) FROM fact_payment p JOIN fact_booking b USING (booking_sk)
     JOIN dim_status s USING (status_sk) WHERE p.amount_quality = 'valid' AND s.status = 'CONFIRMED') AS confirmed_booking_payment_amount,
    (SELECT count(*) FILTER (WHERE s.status = 'CANCELLED') * 1.0 / NULLIF(count(*), 0)
     FROM fact_booking b JOIN dim_status s USING (status_sk)) AS cancellation_rate,
    (SELECT count(*) FILTER (WHERE s.status = 'CONFIRMED') * 1.0 / NULLIF(count(*), 0)
     FROM fact_booking b JOIN dim_status s USING (status_sk)) AS confirmation_rate,
    (SELECT count(DISTINCT booking_sk) * 1.0 / NULLIF((SELECT count(*) FROM fact_booking), 0)
     FROM fact_payment) AS payment_coverage,
    (SELECT sum(amount) / NULLIF(count(DISTINCT booking_sk), 0)
     FROM fact_payment WHERE amount_quality = 'valid') AS avg_valid_payment_per_paid_booking,
    (SELECT count(*) FROM fact_booking b WHERE NOT EXISTS
     (SELECT 1 FROM fact_payment p WHERE p.booking_sk = b.booking_sk)) AS bookings_without_payment;

CREATE VIEW kpi_route AS
WITH flights AS (
    SELECT route_sk, count(*) AS flight_count, avg(duration_minutes) AS avg_duration_minutes,
           stddev_pop(duration_minutes) AS duration_stddev_minutes
    FROM fact_flight WHERE NOT is_unknown_member GROUP BY route_sk
), bookings AS (
    SELECT f.route_sk, count(*) AS booking_count FROM fact_booking b
    JOIN fact_flight f USING (flight_sk) GROUP BY f.route_sk
), payments AS (
    SELECT f.route_sk, sum(p.amount) AS gross_valid_payment_amount
    FROM fact_payment p JOIN fact_booking b USING (booking_sk)
    JOIN fact_flight f USING (flight_sk)
    WHERE p.amount_quality = 'valid' GROUP BY f.route_sk
)
SELECT r.*, COALESCE(f.flight_count, 0) AS flight_count, f.avg_duration_minutes,
       f.duration_stddev_minutes, COALESCE(b.booking_count, 0) AS booking_count,
       p.gross_valid_payment_amount
FROM dim_route r LEFT JOIN flights f USING (route_sk)
LEFT JOIN bookings b USING (route_sk) LEFT JOIN payments p USING (route_sk);

CREATE VIEW kpi_airline AS
SELECT a.airline_sk, a.airline, a.is_unknown, count(f.flight_sk) AS flight_count,
       count(f.flight_sk) * 1.0 / NULLIF((SELECT count(*) FROM fact_flight WHERE NOT is_unknown_member), 0) AS flight_share,
       avg(f.duration_minutes) AS avg_duration_minutes
FROM dim_airline a LEFT JOIN fact_flight f ON a.airline_sk = f.airline_sk AND NOT f.is_unknown_member
GROUP BY a.airline_sk, a.airline, a.is_unknown;

CREATE VIEW kpi_departure_hour AS
SELECT departure_hour, count(*) AS flight_count,
       avg(duration_minutes) AS avg_duration_minutes
FROM fact_flight WHERE NOT is_unknown_member GROUP BY departure_hour;
