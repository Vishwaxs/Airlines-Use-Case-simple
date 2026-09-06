import sys
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def build_notebook():
    notebook = nbformat.v4.new_notebook()
    cells = [
        ('markdown', '# ASG Airlines: evidence walkthrough\n\nThe source profile is recomputed from the workbook. Cleaned results come from the completed pipeline. Historical cloud evidence and Desktop verification are assessed separately.'),
        ('code', '''import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path.cwd()
if ROOT.name == "notebooks":
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from src.kpi import calculate_kpis
from src.profile import profile_source, read_source

manifest_path = ROOT / "reports/run_manifest.json"
if not manifest_path.exists():
    raise RuntimeError("Run python -m src.pipeline with ASG_PII_PEPPER set before this notebook.")
manifest = json.loads(manifest_path.read_text())
assert manifest["status"] == "success"
with tempfile.TemporaryDirectory() as profile_dir:
    profile = profile_source(ROOT / "data/raw/UseCase_Airlines.xlsx", profile_dir)
assert profile["source_sha256"] == manifest["source_sha256"]
raw, _, _ = read_source(ROOT / "data/raw/UseCase_Airlines.xlsx")
pd.DataFrame({name: {"source_rows": item["rows"], "columns": len(item["columns"])}
              for name, item in profile["structure"].items()}).T'''),
        ('markdown', 'SJ192 needs exactly one day added to arrival. The repaired flight lasts 300 minutes and arrives on the departure date.'),
        ('code', '''before = raw["flights"].loc[raw["flights"].flight_id == "SJ192", ["flight_id", "departure_time", "arrival_time"]].assign(stage="source")
flights = pd.read_parquet(ROOT / "data/silver/flights.parquet")
after = flights.loc[flights.flight_id == "SJ192", ["flight_id", "departure_time", "arrival_time", "duration_minutes", "was_corrected", "is_overnight"]].assign(stage="silver")
pd.concat([before, after], ignore_index=True)'''),
        ('markdown', 'Excel stores 1,019 raw durations as time cells and one as a datetime representing a negative serial. Both must be decoded before reconciliation.'),
        ('code', '''pd.DataFrame({"source_type": list(profile["structure"]["flights"]["source_types"]["duration"]),
              "rows": list(profile["structure"]["flights"]["source_types"]["duration"].values())})'''),
        ('markdown', 'Missing amounts and the INVALID sentinel remain separate. Only valid amounts contribute to the payment total.'),
        ('code', '''payment_types = profile["structure"]["payments"]["source_types"]["amount"]
payment_quality = pd.read_parquet(ROOT / "data/silver/payments.parquet").groupby("amount_quality").size()
display(pd.Series(payment_types, name="source_rows").to_frame())
payment_quality.to_frame("silver_rows")'''),
        ('markdown', 'Duplicate flight keys repeat payments in a naive join. The warehouse uses unique flight keys and keeps each payment once.'),
        ('code', '''pd.Series(profile["fanout"], name="measured_result").to_frame()'''),
        ('markdown', 'Survivorship selects one record by completeness, Aadhaar shape, email ordering, then source row. The audit shows ranks without contact values.'),
        ('code', '''audit = pd.read_csv(ROOT / "reports/passenger_survivorship.csv")
example = audit.passenger_id.iloc[0]
audit.loc[audit.passenger_id == example]'''),
        ('markdown', 'The analytical passenger dimension contains a token and demographics. Raw names, contacts and DOB are absent.'),
        ('code', '''passengers = pd.read_csv(ROOT / "data/gold/dim_passenger.csv")
passengers.loc[passengers.passenger_sk != -1].head(3)'''),
        ('markdown', 'These KPIs use the verified final model: 1,003 real flights and all 1,000 bookings. Overnight and red-eye shares use real flights as their denominator. True delay is unavailable.'),
        ('code', '''kpis = calculate_kpis(ROOT / "data/gold/asg_airlines.duckdb")
pd.Series(kpis, name="value").to_frame()'''),
    ]
    notebook.cells = [nbformat.v4.new_markdown_cell(text) if kind == 'markdown'
                      else nbformat.v4.new_code_cell(text) for kind, text in cells]
    notebook.metadata.kernelspec = {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}
    # Use the builder's interpreter; do not depend on a globally installed DuckDB.
    manager = KernelManager(kernel_name='python3')
    manager.kernel_spec.argv = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    client = NotebookClient(notebook, km=manager, timeout=120, resources={'metadata': {'path': str(ROOT)}})
    try:
        client.execute()
    finally:
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
    destination = ROOT / 'notebooks/asg_airlines_walkthrough.ipynb'
    destination.parent.mkdir(exist_ok=True)
    nbformat.write(notebook, destination)
    print(f'Executed {sum(c.cell_type == "code" for c in notebook.cells)} notebook cells: {destination.name}')


if __name__ == '__main__':
    build_notebook()
