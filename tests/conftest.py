"""Every test session gets its own throw-away data folder (database, images, practice workbook)."""
import os, sys, tempfile, shutil
import pytest

_TMP = tempfile.mkdtemp(prefix="checkflow-test-")
os.environ["CHECKFLOW_DATA"] = _TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REFS = os.environ.get("CHECKFLOW_REFS", os.path.join(ROOT, "references"))

def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)

@pytest.fixture(scope="session")
def app_module():
    from checkflow import app as appmod
    return appmod

@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)

@pytest.fixture()
def admin(client):
    r = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return client

@pytest.fixture()
def workbook(tmp_path):
    from checkflow.excel.practice import make_practice
    return make_practice(str(tmp_path / "wb.xlsx"))

def refs_available():
    return os.path.isdir(REFS) and any(f.lower().endswith(".pdf") for f in os.listdir(REFS))
