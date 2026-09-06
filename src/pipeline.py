import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import time
import traceback
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .clean import clean
from .ingest import ingest
from .kpi import calculate_kpis, export_gold
from .logging_setup import configure_logging
from .model import build_model
from .profile import profile_source
from .validate import validate

ROOT = Path(__file__).resolve().parents[1]


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, 'item'):
        return value.item()
    raise TypeError(f'Unsupported manifest type: {type(value).__name__}')


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=_json_default) + '\n', encoding='utf-8')


def write_quality_report(path, source_counts, silver, quarantine, issues, kpis, profile, export_counts):
    lines = ['# Data quality report', '',
             'Issue counts are source-row events. A row can have several issues; do not add these counts to estimate unique bad records.', '',
             '| Table | Source rows | Silver rows | Quarantined rows |', '|---|---:|---:|---:|']
    for name, count in source_counts.items():
        lines.append(f'| {name} | {count} | {len(silver[name])} | {len(quarantine.get(name, []))} |')
    lines += ['', '| Table | Issue | Affected rows | Treatment |', '|---|---|---:|---|']
    for (table, issue, treatment), group in issues.groupby(['table_name', 'issue', 'treatment'], sort=True):
        lines.append(f'| {table} | {issue} | {len(group)} | {treatment} |')
    flights = silver['flights']
    compared = flights['duration_matches_raw'].dropna()
    fanout = profile['fanout']
    exact_removed = int(((issues.table_name == 'flights') & (issues.issue == 'exact_duplicate')).sum())
    conflicted = int(((issues.table_name == 'flights') & (issues.issue == 'conflicting_duplicate_key')).sum())
    unresolved = int(((issues.table_name == 'bookings') & issues.issue.isin(['unavailable_flight_reference', 'missing_flight_reference'])).sum())
    lines += ['', '## Final results', '',
              f"- {len(flights)} real flights; {int(flights['was_corrected'].sum())} timestamp correction(s).",
              f"- {int(flights['is_overnight'].sum())} overnight flights and {int(flights['is_red_eye'].sum())} red-eye departures after duplicate treatment.",
              f'- Raw duration reconciliation: {int(compared.sum())} matches, {int((~compared.astype(bool)).sum())} mismatches, {len(flights) - len(compared)} unparseable values among retained flights.',
              f'- {exact_removed} exact flight copies removed; {conflicted} conflicting-key rows quarantined; {unresolved} bookings flagged for an unknown flight reference.',
              f"- Passenger survivorship retained {len(silver['passengers'])} IDs from {source_counts['passengers']} rows. Duplicate candidates and ranking are recorded in passenger_survivorship.csv.",
              f"- Gross valid payment amount: {('INR ' + format(Decimal(str(kpis['gross_valid_payment_amount'])), ',.2f')) if kpis['gross_valid_payment_amount'] is not None else 'unavailable (no valid amounts)'}. Missing and non-numeric amounts remain NULL.",
              f"- Independent source fan-out check: INR {Decimal(fanout['true_payment_total']):,.2f} becomes INR {Decimal(fanout['naive_three_way_total']):,.2f} in the naive three-way join, a difference of INR {Decimal(fanout['inflation']):,.2f}.",
              '- Silver and analytical payment totals reconcile exactly in the model checks. Payment facts retain a single row per payment_id. Quarantined amounts are excluded from the analytical total.',
              '- Delay minutes cannot be calculated: the source has no scheduled-versus-actual timestamps.',
              f"- kpi_booking_month.csv: {export_counts['kpi_booking_month']} actual year-month periods, grouped by booking date; payments are associated with booking month, not a payment transaction date.",
              '', 'Timestamp durations retain microseconds. Raw-duration reconciliation uses a one-second tolerance; the source report records any smaller differences.']
    for row in flights[flights.was_corrected].itertuples():
        raw_label = 'unparseable' if row.raw_duration_minutes is None else f'{row.raw_duration_minutes:g} minutes'
        lines.append(f'- {row.flight_id}: raw duration {raw_label}; repaired duration {row.duration_minutes:g} minutes; overnight = {row.is_overnight}.')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _publish(work: Path, output: Path):
    """Replace completed artifacts together; restore the prior run if a move fails."""
    relative_paths = [Path('data') / name for name in ['bronze', 'silver', 'quarantine', 'gold']]
    relative_paths += [Path('reports') / name for name in [
        'profile.md', 'profile.json', 'data_quality_report.md', 'passenger_survivorship.csv',
        'run_manifest.json']]
    moved = []
    backups = []
    try:
        for relative in relative_paths:
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = work / 'previous' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                destination.replace(backup)
                backups.append((backup, destination))
            (work / relative).replace(destination)
            moved.append(destination)
    except Exception:
        for destination in reversed(moved):
            relative = destination.relative_to(output)
            rollback = work / 'rollback' / relative
            rollback.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(rollback)
        for backup, destination in reversed(backups):
            backup.replace(destination)
        raise


def run_pipeline(input_path=ROOT / 'data/raw/UseCase_Airlines.xlsx', output_dir=ROOT, pepper=None):
    input_path, output_dir = Path(input_path).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:12]
    logger = configure_logging(output_dir / 'reports/logs', run_id)
    manifest = {'run_id': run_id, 'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
                'source_file': input_path.name, 'stages': [],
                'versions': {name: importlib.metadata.version(name) for name in ['pandas', 'duckdb', 'openpyxl', 'pyarrow']}}
    work = output_dir / '.work' / run_id
    lock = output_dir / '.pipeline.lock'
    lock_handle = None
    stage = None
    try:
        lock_handle = lock.open('x')
        lock_handle.write(run_id)
        lock_handle.flush()
        pepper = pepper if pepper is not None else os.environ.get('ASG_PII_PEPPER')
        if not pepper or len(pepper) < 32:
            raise ValueError('ASG_PII_PEPPER must contain at least 32 characters')
        manifest['source_sha256'] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        (work / 'reports').mkdir(parents=True)

        def start(name, rows_in):
            nonlocal stage
            stage = {'name': name, 'started_at': datetime.now(timezone.utc).isoformat(),
                     'rows_in': rows_in, 'rows_out': {}, 'rows_quarantined': {}, 'status': 'running'}
            manifest['stages'].append(stage)
            logger.info('stage=%s status=started', name)
            return time.perf_counter()

        def finish(started, rows_out, quarantined=None):
            stage.update(ended_at=datetime.now(timezone.utc).isoformat(),
                         duration_seconds=round(time.perf_counter() - started, 6), rows_out=rows_out,
                         rows_quarantined=quarantined or {}, status='success')
            logger.info('stage=%s status=success rows=%s', stage['name'], rows_out)

        started = start('ingest', {})
        tables = ingest(input_path, work / 'data/bronze', run_id)
        source_counts = {name: len(frame) for name, frame in tables.items()}
        finish(started, source_counts)

        started = start('validate', source_counts)
        issues = validate(tables, ROOT / 'config/validation_rules.yaml')
        profile = profile_source(input_path, work / 'reports')
        finish(started, source_counts)

        started = start('clean', source_counts)
        silver, quarantine, issues, survivorship = clean(tables, issues, pepper)
        for layer, frames in [('silver', silver), ('quarantine', quarantine)]:
            directory = work / 'data' / layer
            directory.mkdir(parents=True, exist_ok=True)
            for name, frame in frames.items():
                if layer == 'silver':
                    frame.to_parquet(directory / f'{name}.parquet', index=False)
                else:
                    # CSV retains mixed raw durations in the restricted quarantine boundary.
                    frame.to_csv(directory / f'{name}.csv', index=False)
        issues.to_parquet(work / 'data/silver/dq_issues.parquet', index=False)
        survivorship.to_csv(work / 'reports/passenger_survivorship.csv', index=False)
        silver_counts = {name: len(frame) for name, frame in silver.items()}
        quarantine_counts = {name: len(frame) for name, frame in quarantine.items()}
        finish(started, silver_counts, quarantine_counts)

        started = start('model', silver_counts)
        database = work / 'data/gold/asg_airlines.duckdb'
        build_model(silver, issues, database)
        finish(started, silver_counts)

        started = start('kpi', silver_counts)
        kpis = calculate_kpis(database)
        finish(started, {'kpi_summary': 1})

        started = start('export', silver_counts)
        export_counts = export_gold(database, work / 'data/gold')
        write_quality_report(work / 'reports/data_quality_report.md', source_counts, silver,
                             quarantine, issues, kpis, profile, export_counts)
        finish(started, export_counts)
        manifest.update(status='success', ended_at=datetime.now(timezone.utc).isoformat(),
                        source_rows=source_counts, silver_rows=silver_counts,
                        quarantine_rows=quarantine_counts, gold_rows=export_counts, kpis=kpis,
                        gold_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted((work / 'data/gold').glob('*.csv'))})
        _write_json(work / 'reports/run_manifest.json', manifest)
        _publish(work, output_dir)
        logger.info('run_id=%s status=success', run_id)
        return manifest
    except Exception as exc:  # noqa: BLE001 - Redact third-party errors that may include source PII.
        if stage is not None and stage['status'] == 'running':
            stage.update(status='failed', ended_at=datetime.now(timezone.utc).isoformat(),
                         duration_seconds=round(time.perf_counter() - started, 6))
        last_frame = traceback.extract_tb(exc.__traceback__)[-1]
        location = f'{Path(last_frame.filename).name}:{last_frame.lineno} ({last_frame.name})'
        manifest.update(status='failed', ended_at=datetime.now(timezone.utc).isoformat(),
                        error_type=type(exc).__name__, error_location=location)
        _write_json(output_dir / 'reports/failed_runs' / f'{run_id}.json', manifest)
        logger.error('run_id=%s stage=%s status=failed error_type=%s location=%s', run_id,
                     stage['name'] if stage else 'setup', type(exc).__name__, location)
        # Library exceptions can contain source cell values. Keep logs and CLI PII-safe.
        raise RuntimeError(f"Pipeline failed at {stage['name'] if stage else 'setup'} ({type(exc).__name__}); check inputs, ASG_PII_PEPPER and the failed-run manifest") from None
    finally:
        if lock_handle is not None:
            lock_handle.close()
            lock.unlink(missing_ok=True)
        if work.exists() and work.resolve().is_relative_to((output_dir / '.work').resolve()):
            shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description='Run the ASG Airlines workbook batch.')
    parser.add_argument('--input', type=Path, default=ROOT / 'data/raw/UseCase_Airlines.xlsx')
    parser.add_argument('--output-dir', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        run_pipeline(args.input, args.output_dir)
    except RuntimeError as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
