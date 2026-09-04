import os
import sys
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
        db_path.unlink()
    yield
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
