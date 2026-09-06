from pathlib import Path

import openpyxl
import pandas as pd


def test_no_raw_pii_in_gold_or_reports(pipeline_output):
    output, _ = pipeline_output
    source = Path(__file__).resolve().parents[1] / 'data/raw/UseCase_Airlines.xlsx'
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    prohibited = {'first_name', 'last_name', 'email', 'phone', 'aadhaar_id', 'date_of_birth',
                  'passport_number', 'emergency_contact_name', 'emergency_contact_phone', 'masked_name'}
    raw_values = set()
    for sheet_name in ['passengers', 'bookings']:
        rows = workbook[sheet_name].values
        header = next(rows)
        pii_indices = [i for i, name in enumerate(header) if name in prohibited]
        for row in rows:
            for i in pii_indices:
                if row[i] is not None and isinstance(row[i], str):
                    raw_values.add(row[i])
    workbook.close()
    for csv in (output / 'data/gold').glob('*.csv'):
        frame = pd.read_csv(csv, dtype=str, keep_default_na=False)
        assert not prohibited.intersection(frame.columns), csv.name
        values = set(frame.to_numpy().ravel())
        assert not raw_values.intersection(values), f'PII found in {csv.name}'
    # Audit reports can name source columns, but may not contain actual identity/contact values.
    sensitive = {v for v in raw_values if '@' in v or v.startswith('+91-') or (v.isdigit() and len(v) == 12)}
    for path in list((output / 'reports').glob('*.md')) + list((output / 'reports').glob('*.json')) + list((output / 'reports').glob('*.csv')):
        text = path.read_text(encoding='utf-8')
        assert not any(value in text for value in sensitive), f'PII found in {path.name}'
