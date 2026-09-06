# Execution flow

Entry point: `python -m src.pipeline --input data/raw/UseCase_Airlines.xlsx --output-dir .`

`src.pipeline.run_pipeline(input_path, output_dir, pepper=None)` coordinates a full refresh. Its explicit `pepper` argument supports tests; normal CLI runs use `ASG_PII_PEPPER` from the environment.

| Transition | Input and result | Important work |
|---|---|---|
| `ingest.ingest()` | Workbook → DataFrames and `data/bronze/*.jsonl` | Preserve mixed source cell types; attach run ID, sheet, Excel row and UTC ingestion time. Ignore wholly empty padding only. |
| `validate.validate()` and `profile.profile_source()` | Source DataFrames/workbook → issues and `reports/profile.md`/`.json` | Fail missing structure; flag values, keys, ranges and references; independently measure source totals before cleaning. `config/validation_rules.yaml` stores short allowlists and limits. |
| `clean.clean()` | DataFrames and issues → silver tables, quarantine and survivorship evidence | Correct time, distinguish duplicate cases, retain incomplete amounts and apply `pii` functions. |
| `model.build_model()` | Silver → `data/gold/asg_airlines.duckdb` | Execute dimensions, facts and KPI SQL in a transaction; verify row counts, relationships and payment cents. |
| `kpi.calculate_kpis()` | DuckDB views → KPI values | Read SQL measures whose denominators are explicit. |
| `kpi.export_gold()` | DuckDB tables/views and the booking-month query → 14 ordered gold CSVs | Export the fixed analytical allowlist, including 13 actual booking year-month periods. |

`sql/01_dimensions.sql` builds the five dimensions. `02_facts.sql` creates one row per accepted flight, booking and payment, plus an unknown flight member. `03_kpi_views.sql` computes summary, route, airline and departure-hour measures. The monthly query in `src/kpi.py` joins bookings to `dim_date` using `booking_date_sk`, aggregates payments per booking, and groups by year-month. Route payments follow payment → unique booking → unique flight, so they cannot repeat source duplicate flight rows.

The runner records stage times, counts and status in `reports/run_manifest.json` and writes log messages through `src/logging_setup.py`. A failed stage raises an exception and creates a safe failed-run manifest. Work is isolated under `.work/<run-id>`; a local lock prevents concurrent writers, and only a completed run replaces the published dataset. A failed publication restores the prior files. `reports/data_quality_report.md` explains source issues and outcomes. Quarantined rows go to `data/quarantine/`, with a reason and run/source trace.

Review in this order: `reports/profile.md` → `src/pipeline.py` → `src/clean.py` → the three SQL files → `reports/data_quality_report.md` → `powerbi/BUILD_GUIDE.md`. The notebook calls the same modules; it does not maintain a second implementation.
