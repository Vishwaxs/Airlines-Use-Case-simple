from pathlib import Path

import duckdb
import pandas as pd


def build_model(silver: dict[str, pd.DataFrame], issues: pd.DataFrame, database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    sql_dir = Path(__file__).resolve().parents[1] / 'sql'
    with duckdb.connect(str(database)) as con:
        for name, frame in silver.items():
            con.register(f'silver_{name}', frame)
        con.register('silver_issues', issues)
        con.execute('BEGIN')
        try:
            for script in ['01_dimensions.sql', '02_facts.sql', '03_kpi_views.sql']:
                con.execute((sql_dir / script).read_text(encoding='utf-8'))
            checks = [
                ('flight rows', 'SELECT count(*) FROM fact_flight WHERE NOT is_unknown_member', len(silver['flights'])),
                ('booking rows', 'SELECT count(*) FROM fact_booking', len(silver['bookings'])),
                ('payment rows', 'SELECT count(*) FROM fact_payment', len(silver['payments'])),
                ('passenger rows', 'SELECT count(*) FROM dim_passenger WHERE passenger_sk <> -1', len(silver['passengers'])),
                ('payment cents', "SELECT COALESCE(sum(amount) * 100, 0) FROM fact_payment WHERE amount_quality = 'valid'",
                 int(silver['payments']['amount_cents'].sum())),
            ]
            for name, query, expected in checks:
                if con.execute(query).fetchone()[0] != expected:
                    raise ValueError(f'Model check failed: {name}')
            for child, key, parent in [
                ('fact_booking', 'flight_sk', 'fact_flight'),
                ('fact_booking', 'passenger_sk', 'dim_passenger'),
                ('fact_booking', 'status_sk', 'dim_status'),
                ('fact_booking', 'booking_date_sk', 'dim_date'),
                ('fact_payment', 'booking_sk', 'fact_booking'),
                ('fact_flight', 'airline_sk', 'dim_airline'),
                ('fact_flight', 'route_sk', 'dim_route'),
                ('fact_flight', 'departure_date_sk', 'dim_date'),
            ]:
                parent_key = 'date_sk' if key.endswith('date_sk') else key
                query = f'SELECT count(*) FROM {child} c LEFT JOIN {parent} p ON c.{key} = p.{parent_key} WHERE p.{parent_key} IS NULL'
                if con.execute(query).fetchone()[0]:
                    raise ValueError(f'Model relationship failed: {child}.{key}')
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
