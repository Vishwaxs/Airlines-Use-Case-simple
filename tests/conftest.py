from pathlib import Path

import pytest

from src.pipeline import run_pipeline


@pytest.fixture(scope='session')
def pipeline_output(tmp_path_factory):
    source = Path(__file__).resolve().parents[1] / 'data/raw/UseCase_Airlines.xlsx'
    if not source.exists():
        pytest.fail('Place the authorized source workbook at data/raw/UseCase_Airlines.xlsx before testing')
    output = tmp_path_factory.mktemp('pipeline')
    manifest = run_pipeline(source, output, pepper='unit-test-pepper-for-synthetic-checks-only')
    return output, manifest
