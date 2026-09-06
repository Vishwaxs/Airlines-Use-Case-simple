# Decisions

## D-001 - Use pandas, SQL and DuckDB

Context: The workbook contains four tables with roughly one thousand rows each. Mixed Excel cell types and duplicate keys need explicit inspection.

Decision: Use openpyxl to preserve source cell types, pandas for row cleaning, and DuckDB for the analytical model and SQL KPIs. Keep one Python entry point.

Alternatives considered: pandas alone; a distributed Spark pipeline.

Why: SQL makes fact grains and aggregation easy to inspect. The measured volume fits in memory; distributing this work adds setup without solving a data problem.

Implementation: `src/ingest.py:ingest`, `src/clean.py:clean`, `src/model.py:build_model`, `sql/`, `src/pipeline.py:run_pipeline`.

Consequence: This is a single-process, single-writer batch. Larger sources need measured memory/runtime limits before changing the stack. The Azure adapter invokes the same pipeline; historical cloud runs and their verification limits are recorded separately.

## D-002 - Preserve source types in bronze

Context: Excel stores duration as both time and datetime cells. It stores Aadhaar as text, including leading zeroes. Automatic pandas inference can erase that distinction.

Decision: Read with openpyxl. Write bronze as JSON Lines with each cell's original type and value, plus source row, sheet and run metadata. Write typed, privacy-reduced silver as Parquet.

Alternatives considered: Direct pandas Excel import; coercing all bronze values into one Parquet type.

Why: A type-tagged source record is small and auditable for this workbook. Blank formatting-only rows and unnamed empty columns are not business data.

Implementation: `src/ingest.py:ingest`, `reports/profile.md`.

Consequence: Bronze remains restricted personal data and is excluded from Git. The original workbook is retained byte-for-byte for exact reproduction.

## D-003 - Derive duration from timestamps

Context: SJ192 has a negative interval; Excel's mixed duration types repeat that mistake.

Decision: Subtract departure from arrival. For negative intervals only, add one day to arrival. Quarantine results outside 0 < minutes <= 1,440. Preserve microseconds and compare the decoded raw duration within one second.

Alternatives considered: Trust the duration cell; shift every overnight arrival; round durations to whole minutes.

Why: Correctly dated overnight flights already contain the following day. A blanket shift would add an extra day. SJ192 becomes 300 minutes and arrives on the same date as departure.

Implementation: `src/clean.py:flight_timing`, `raw_duration_minutes`; `config/validation_rules.yaml`; `tests/test_clean.py`.

Consequence: `is_overnight` compares corrected dates; `is_red_eye` checks departure hour 22 through 4. They remain separate flags. No scheduled/actual pair exists, so anomalies replace the unavailable delay metric.

## D-004 - Separate exact copies from conflicting flight IDs

Context: Fifteen duplicate pairs are identical; 6F250 has two incompatible schedules. Two bookings reference it.

Decision: Keep one exact copy. Quarantine every conflicting row and retain its bookings with flight_sk = -1.

Alternatives considered: Keep the first flight ID encountered; drop bookings without a clean flight.

Why: Workbook order does not establish the correct schedule. Removing bookings would lose valid transactions.

Implementation: `src/validate.py:validate`, `src/clean.py:clean`, `sql/02_facts.sql`.

Consequence: There are 1,003 real flights and one unknown placeholder. Flight KPIs exclude the placeholder. Revenue linked to an unresolved flight appears under the UNKNOWN route instead of disappearing.

## D-005 - Make passenger survivorship repeatable

Context: Thirty-six passenger ID groups contain conflicting identity/contact fields. No update timestamp establishes authority.

Decision: Prefer fewer nulls, then a source Aadhaar representation with twelve digits, then the lexicographically smallest email. Use lowest source row only for remaining ties. Record every duplicate candidate and its rank without contact values.

Alternatives considered: Keep the first row; merge fields from different identities.

Why: The selected record can be explained and reproduced without inventing a composite identity. Stable age and gender do not resolve the conflicting identities.

Implementation: `src/clean.py:passenger_survivors`, `reports/passenger_survivorship.csv`.

Consequence: 1,039 source rows become 1,000 passengers. This rule chooses a record; it does not certify that record as correct.

## D-006 - Tokenize identity and remove unused PII

Context: Passenger and booking sheets contain names, contact fields, Aadhaar, DOB and passports. The KPIs do not need those values.

Decision: Restore the twelve-digit Aadhaar shape before HMAC-SHA-256 with an external pepper. Silver retains masked initials; gold omits names entirely. Remove contacts, DOB, passports and emergency details. Keep age, age band and gender.

Alternatives considered: Plain hashing; exporting partially masked contacts; keeping DOB for downstream users.

Why: A secret-key HMAC reduces identifier guessing, while omission avoids distributing unnecessary personal data. The workbook already retains leading zeroes, but normalization protects numeric inputs too.

Implementation: `src/pii.py`, `sql/01_dimensions.sql`, `.env.example`, `tests/test_pii.py`, `tests/test_no_pii_leak.py`.

Consequence: Tokens are pseudonymous and depend on the pepper and survivor. Raw, bronze and quarantine remain restricted. Local filesystem access and Azure RBAC must be configured by the operator.

## D-007 - Retain incomplete business records

Context: Airline, status, surname and payment amount have missing or sentinel values. These failures do not necessarily invalidate the transaction.

Decision: Retain useful rows and issue flags. Airline null and sentinel map to UNKNOWN but remain separate issues. Status null maps to UNKNOWN; unsupported nonempty values map to INVALID. Keep missing/non-numeric payment amounts NULL and classify them separately.

Alternatives considered: Delete incomplete rows; impute zero amounts; combine all issues under one label.

Why: Deletion changes transaction counts and zero imputation misstates the evidence. Structurally unusable keys, timestamps and ambiguous records are quarantined with reasons.

Implementation: `src/validate.py:validate`, `classify_amount`, `src/clean.py:clean`, `config/validation_rules.yaml`.

Consequence: All 1,000 bookings and payment records survive this workbook. Only 922 valid amounts contribute to the payment total. Identifiers and city codes follow strict source patterns; arbitrary malformed route text is quarantined.

## D-008 - Keep payment grain and exact currency

Context: Duplicate flight joins inflate INR 7,385,142.98 to INR 7,593,758.92. Multiple payment rows per booking are legitimate.

Decision: Store one row per payment, linked to one unique booking. Bookings link to unique flight keys. Parse currency with Decimal into integer cents and store DuckDB DECIMAL(18,2). Aggregate route flights, bookings and payments separately.

Alternatives considered: A single joined wide table; one arbitrary payment per booking; floating-point money sums.

Why: The model removes accidental fan-out while preserving legitimate multiple payments. Exact cents make reconciliation unambiguous.

Implementation: `src/validate.py:classify_amount`, `src/model.py:build_model`, `sql/02_facts.sql`, `sql/03_kpi_views.sql`, `tests/test_model.py`.

Consequence: Required grain and reference checks run before publication. The model is a small fact constellation with shared dimensions; payments follow booking filters, and flight KPIs remain at flight grain.

## D-009 - Publish only a completed local batch

Context: A failed refresh must not replace a previously usable dataset.

Decision: Build under a run-specific work directory, hold a single-writer lock, and publish only after validation, model checks and exports succeed. Restore previous paths if a publication move fails. Record failed runs separately with safe stage/error information.

Alternatives considered: Overwrite final CSVs as each stage runs; introduce a scheduler or workflow framework.

Why: A few explicit functions provide enough failure control for this assessment. Identical input and pepper yield identical sorted gold CSVs.

Implementation: `src/pipeline.py:run_pipeline`, `_publish`; `reports/run_manifest.json`; `tests/test_model.py`.

Consequence: Consumers should read after the CLI succeeds. Local publication is a guarded multi-file move, not a database transaction across directories; concurrent readers are outside this batch contract. Run IDs and audit timestamps change on every run.

## D-010 - Run the existing batch on Azure

Context: The assignment prefers Azure and requires a working Power BI report. Local transformations, cloud publication and report interaction need separate checks.

Decision: Keep the Python transformations and add a download/run/upload adapter. Retain the gold CSVs, DAX definitions and Desktop build instructions.

Alternatives considered: Reimplement cleaning in a second processing stack; treat static images as report evidence instead of a built report.

Why: One workbook does not require a second transformation implementation. A cloud run must be compared with its corresponding local baseline, and a Power BI report must be opened and refreshed in Desktop.

Implementation: `src/azure_adapter.py`, `tools/deploy_azure.ps1`, `powerbi/BUILD_GUIDE.md`, `powerbi/measures.dax`.

Consequence: Historical Azure evidence covers the previous 13-file export. The revised pipeline exports 14 CSVs, including the 13-period monthly booking extract, and needs a new cloud comparison. The working PBIX and genuine screenshots remain unfinished.

## D-011 - Record the Container Apps deployment path

Context: `reports/azure/deployment_manifest.json` records East Asia resources in `rg-asg-airlines-ea`. It is a saved deployment record; the local fixes do not recheck those resources.

Decision: The supplied deployment script provisions ADLS Gen2 storage, Key Vault, a user-assigned managed identity, a registry, Log Analytics and a manually triggered Container Apps Job. It imports a Python base image and references its digest. The job installs dependencies at startup, downloads `restricted/app/app.tar.gz`, and invokes the adapter with the pepper supplied through a Key Vault reference.

Why: This wrapper can invoke the existing batch without changing its data transformations.

Implementation: `src/azure_adapter.py`, `tools/deploy_azure.ps1`, `tools/package_app.py`, `reports/azure/deployment_manifest.json`. The standalone `Dockerfile` defines a separate image-build path; the deployment script uses the imported base image and downloaded package.

Consequence: The base-image digest does not identify the mutable application package. Azure dependencies installed by the script are not pinned. Historical evidence does not establish the current package version, current resource configuration, subscription restrictions or current costs.

## D-012 - Publish Azure runs through a conditional pointer

Context: Readers need a completed run to select while another run uploads its files.

Decision: The adapter reads the workbook from `raw`, uploads gold CSVs/DuckDB/run metadata to `analytics`, and sends bronze, silver, quarantine, logs and profile outputs to `restricted`. Files use `runs/<run_id>/` prefixes. The adapter reads the initial `analytics/latest.json` ETag and conditions its final update on that value; initial creation fails if a pointer already exists.

Why: A failure before the pointer update leaves readers on the previous selected run. A conflicting ETag is reported as a failed publication.

Implementation: `src/azure_adapter.py:get_latest_etag`, `upload_file_and_verify`, `update_latest_pointer`, `run_adapter`.

Consequence: The upload helper compares blob sizes and returns local hashes; it does not download remote bytes to verify those hashes. It allows overwrite, so run prefixes are not enforced immutable storage. The historical rerun record checks blob counts and selected KPIs; it does not establish prior-content immutability or test an ETag conflict. The Power BI project currently reads a local folder and does not consume `latest.json`.

## D-013 - Retain the Power BI project for Desktop completion

Context: The retained project contains 12 table definitions, 26 measures, 8 active single-direction relationships and four page definitions. Static structure does not establish a working Power BI report.

Decision: Keep the report definition in source control as a PBIP project so the semantic model and page layout are reviewable as text, and publish the built `ASG_Airlines.pbix` alongside it. Source-query column declarations were aligned with the gold exports before the model was refreshed in Desktop.

Why: Separate flight, booking and payment grains and one-direction relationships make filter paths and payment totals inspectable. Each displayed KPI still requires a runtime comparison with the selected run.

Implementation: `powerbi/ASG_Airlines.pbip`, `powerbi/ASG_Airlines.Report/`, `powerbi/ASG_Airlines.SemanticModel/`, `powerbi/measures.dax`, `powerbi/BUILD_GUIDE.md`, `powerbi/VERIFICATION.md`.

Consequence: Existing M queries reference nonexistent source columns and use local `SourceFolder` imports; Azure parameters are unused. Page definitions, refresh, DAX results, slicer behavior and screenshots remain unverified in Desktop. The source issue total to reconcile is 714, not the unsupported 1,048 in the removed dashboard material.
