import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Zanim zaimportujemy aplikację.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="helpersi_test_")
os.environ["COOKIE_SECURE"] = "0"
os.environ["ADMIN_SECRET"] = "test-admin-secret"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("BOOTSTRAP_BOOTHS", None)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Świeża baza na każdy test."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import auth
    from app.main import app
    auth.throttle.reset()
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def conn(client):
    from app import db
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"login": "admin", "password": "test-admin-secret"})
    assert r.status_code == 200
    return client


@pytest.fixture
def booth(admin):
    """Stoisko c13 oraz konto wolontariusza tester / tajne-haslo1; zwraca id stoiska."""
    r = admin.post("/api/admin/booths", json={"id": "c13", "name": "Budynek C-13"})
    assert r.status_code == 201
    r = admin.post("/api/admin/volunteers", json={"login": "tester", "password": "tajne-haslo1"})
    assert r.status_code == 201
    return "c13"


@pytest.fixture
def other_clients(client):
    """Zwraca fabrykę niezależnych klientów (osobne ciasteczka) na tej samej aplikacji."""
    from fastapi.testclient import TestClient
    from app.main import app
    made = []

    def factory():
        c = TestClient(app)
        c.__enter__()
        made.append(c)
        return c
    yield factory
    for c in made:
        c.__exit__(None, None, None)
