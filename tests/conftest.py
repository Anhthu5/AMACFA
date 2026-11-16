"""Isolate the local audit state from environment settings and previous tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amacfa.config import DEMO_ANALYST, DEMO_REVIEWER, Settings
from main import create_app

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        state_dir=tmp_path,
        graph_backend="local",
        vector_backend="local",
        llm_backend="offline",
        demo_mode=True,
        max_upload_bytes=1024,
        analyst_token=DEMO_ANALYST,
        reviewer_token=DEMO_REVIEWER,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as active:
        yield active


@pytest.fixture
def mixed():
    return (DATA / "invoices_mixed.csv").read_bytes()


@pytest.fixture
def clean():
    return (DATA / "invoices_clean.csv").read_bytes()
