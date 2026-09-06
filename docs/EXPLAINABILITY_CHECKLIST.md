# Explainability checklist

| Concept | Where implemented | What it does in plain language |
|---|---|---|
| Ingestion | `src/ingest.py:ingest` | Read each sheet and keep the original value type and Excel row number. |
| Validation | `src/validate.py:validate`; `config/validation_rules.yaml` | Stop if required structure is absent; record row problems for treatment. |
| Flight duplicates | `src/validate.py`; `src/clean.py` | Keep one exact copy, but set aside every conflicting copy of the same ID. |
| Passenger survivorship | `src/clean.py`; `reports/passenger_survivorship.csv` | Rank duplicate candidates with repeatable rules and record which row won. |
| Overnight correction | `src/clean.py` | Add one day only when arrival is earlier than departure, then calculate minutes again. |
| Red-eye classification | `src/clean.py` | Mark departures from 22:00 through 04:59 independently of arrival date. |
| PII tokenization | `src/pii.py:normalize_aadhaar`, `passenger_token` | Restore identifier width and replace the value with a secret-keyed token. |
| Payment grain | `sql/02_facts.sql:fact_payment` | Store each payment once, even when a booking has several payments. |
| Analytical model | `sql/01_dimensions.sql`, `02_facts.sql` | Connect facts to unique keys and keep unresolved flight bookings under an unknown member. |
| KPI calculation | `sql/03_kpi_views.sql` | Sum and average the intended rows using stated denominators. |
| Pipeline execution | `src/pipeline.py:run_pipeline` | Run each stage in order and record its result. |
| Quarantine | `src/clean.py`; `data/quarantine/` | Preserve unusable or ambiguous rows separately with their reason. |

Be able to explain SJ192's 300-minute correction, why 6F250's two bookings remain, and why summing the source three-way join overstates payments by INR 208,615.94. Explain the 606-booking denominator for valid-payment averages, the 13 year-month periods, and the 714 overlapping source issue events. Be able to say why cloud deployment was scoped out and where the stage boundaries would map onto it.
