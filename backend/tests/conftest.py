import os
import tempfile
from datetime import date

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["AUTH_ENABLED"] = "false"  # test_auth.py switches it on for its own tests
os.environ["SEED_DEMO_DATA"] = "false"  # the client fixture seeds with a fixed date so answers never change

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_demo  # noqa: E402

END = date(2026, 10, 26)  # a Monday; the latest business day in the test data


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        with SessionLocal() as db:
            seed_demo(db, end=END)
        yield c
