import gc
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ["RECOVERAI_DATABASE_URL"] = "sqlite:///./test_recoverai.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    db_path = settings.sqlite_path
    if db_path.exists():
        _safe_delete(db_path)
    yield
    gc.collect()
    # Close any lingering sqlite3 connections
    sqlite3.connect(":memory:").close()
    gc.collect()
    if db_path.exists():
        _safe_delete(db_path)


def _safe_delete(path: Path, retries: int = 5, delay: float = 0.1) -> None:
    for _ in range(retries):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(delay)
            gc.collect()
    # Final attempt — allow it to fail silently in teardown
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
