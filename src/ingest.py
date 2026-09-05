import json
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pandas as pd


def ingest(workbook_path: Path, bronze_dir: Path, run_id: str) -> dict[str, pd.DataFrame]:
    """Read Excel cell values without pandas' automatic identifier conversion."""
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    tables = {}
    bronze_dir.mkdir(parents=True, exist_ok=True)
    ingested_at = datetime.now(timezone.utc).isoformat()
    try:
        for sheet in workbook:
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, ())
            active = [(i, str(name).strip()) for i, name in enumerate(header) if name is not None]
            names = [name for _, name in active]
            if len(names) != len(set(names)):
                raise ValueError(f"Duplicate column names in sheet {sheet.title}")
            records = []
            for row_number, row in enumerate(rows, start=2):
                if all(value is None for value in row):
                    continue
                if any(value is not None for i, value in enumerate(row) if i >= len(header) or header[i] is None):
                    raise ValueError(f"Data under an unnamed column in sheet {sheet.title}")
                record = {name: row[i] for i, name in active}
                record.update(source_row=row_number, source_sheet=sheet.title, run_id=run_id,
                              ingested_at=ingested_at)
                records.append(record)
            tables[sheet.title] = pd.DataFrame(records, columns=names + [
                'source_row', 'source_sheet', 'run_id', 'ingested_at'])
            # JSON preserves mixed types as tagged cells; Parquet would coerce Excel times.
            with (bronze_dir / f"{sheet.title}.jsonl").open('w', encoding='utf-8') as handle:
                for record in records:
                    cells = {name: {'type': type(record[name]).__name__,
                                    'value': record[name] if record[name] is None or isinstance(record[name], (str, int, float, bool))
                                    else record[name].isoformat()} for name in names}
                    handle.write(json.dumps({'cells': cells, 'source_row': record['source_row'],
                                             'source_sheet': sheet.title, 'run_id': run_id,
                                             'ingested_at': ingested_at}, ensure_ascii=False) + '\n')
    finally:
        workbook.close()
    return tables

