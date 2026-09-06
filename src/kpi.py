from pathlib import Path

import duckdb

EXPORT_TABLES = [
    'dim_date', 'dim_airline', 'dim_route', 'dim_passenger', 'dim_status',
    'fact_flight', 'fact_booking', 'fact_payment', 'dq_issue_summary',
    'kpi_summary', 'kpi_route', 'kpi_airline', 'kpi_departure_hour', 'kpi_booking_month',
]

BOOKING_MONTH_SQL = """
WITH payments_by_booking AS (
    SELECT booking_sk, sum(amount) AS valid_amount
    FROM fact_payment WHERE amount_quality = 'valid' GROUP BY booking_sk
)
SELECT d.year, d.month, d.year_month AS month_label, count(*) AS bookings,
       sum(p.valid_amount) AS gross_valid_payment_amount,
       sum(CASE WHEN s.status = 'CONFIRMED' THEN p.valid_amount END) AS confirmed_payment_amount
FROM fact_booking b
JOIN dim_date AS d ON d.date_sk = b.booking_date_sk
JOIN dim_status s ON s.status_sk = b.status_sk
LEFT JOIN payments_by_booking p ON p.booking_sk = b.booking_sk
GROUP BY d.year, d.month, d.year_month
"""


def calculate_kpis(database: Path) -> dict:
    with duckdb.connect(str(database), read_only=True) as con:
        result = con.execute('SELECT * FROM kpi_summary')
        return dict(zip([col[0] for col in result.description], result.fetchone()))


def export_gold(database: Path, gold_dir: Path) -> dict[str, int]:
    gold_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    with duckdb.connect(str(database), read_only=True) as con:
        for name in EXPORT_TABLES:
            query = BOOKING_MONTH_SQL if name == 'kpi_booking_month' else f'SELECT * FROM {name}'
            # Table names are a fixed allowlist; file paths are bound parameters.
            con.execute(f'COPY ({query} ORDER BY ALL) TO ? (HEADER, DELIMITER \',\')',
                        [str(gold_dir / f'{name}.csv')])
            counts[name] = con.execute(f'SELECT count(*) FROM ({query})').fetchone()[0]
    return counts
