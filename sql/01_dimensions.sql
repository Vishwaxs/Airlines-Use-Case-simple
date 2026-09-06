CREATE TABLE dim_date AS
WITH bounds AS (
    SELECT min(d) AS first_date, max(d) AS last_date FROM (
        SELECT CAST(booking_date AS DATE) d FROM silver_bookings
        UNION ALL SELECT CAST(departure_time AS DATE) FROM silver_flights
        UNION ALL SELECT CAST(arrival_time AS DATE) FROM silver_flights
    )
), dates AS (
    SELECT CAST(unnest(generate_series(first_date, last_date, INTERVAL 1 DAY)) AS DATE) AS date
    FROM bounds
)
SELECT CAST(strftime(date, '%Y%m%d') AS INTEGER) AS date_sk, date,
       year(date) AS year, month(date) AS month, strftime(date, '%Y-%m') AS year_month,
       day(date) AS day, dayofweek(date) AS weekday
FROM dates
UNION ALL SELECT -1, NULL, NULL, NULL, 'UNKNOWN', NULL, NULL;
ALTER TABLE dim_date ADD PRIMARY KEY (date_sk);

CREATE TABLE dim_airline AS
SELECT -1::BIGINT AS airline_sk, 'UNKNOWN' AS airline, true AS is_unknown
UNION ALL
SELECT row_number() OVER (ORDER BY airline), airline, false
FROM (SELECT DISTINCT airline FROM silver_flights WHERE airline <> 'UNKNOWN');
ALTER TABLE dim_airline ADD PRIMARY KEY (airline_sk);

CREATE TABLE dim_route AS
SELECT -1::BIGINT AS route_sk, 'UNKNOWN' AS source, 'UNKNOWN' AS destination,
       'UNKNOWN' AS route
UNION ALL
SELECT row_number() OVER (ORDER BY source, destination), source, destination,
       source || ' - ' || destination
FROM (SELECT DISTINCT source, destination FROM silver_flights);
ALTER TABLE dim_route ADD PRIMARY KEY (route_sk);

CREATE TEMP TABLE passenger_lookup AS
SELECT row_number() OVER (ORDER BY passenger_id) AS passenger_sk, * FROM silver_passengers;
CREATE TABLE dim_passenger AS
SELECT passenger_sk, passenger_token, age, age_band, gender FROM passenger_lookup
UNION ALL SELECT -1, 'UNKNOWN', NULL, 'UNKNOWN', 'UNKNOWN';
ALTER TABLE dim_passenger ADD PRIMARY KEY (passenger_sk);

CREATE TABLE dim_status AS
SELECT * FROM (VALUES
    (-1, 'UNKNOWN', false), (1, 'CONFIRMED', true), (2, 'CANCELLED', true),
    (3, 'PENDING', true), (4, 'INVALID', false)
) AS statuses(status_sk, status, is_valid);
ALTER TABLE dim_status ADD PRIMARY KEY (status_sk);
