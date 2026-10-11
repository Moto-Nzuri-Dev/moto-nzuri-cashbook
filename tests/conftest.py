import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="cashbook-test-")
os.environ.setdefault("DATA_DIR", _tmp)
if os.getenv("TEST_DATABASE_URL"):          # run the suite against Postgres too
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PW = "Strong#Pass1"


class Client(TestClient):
    """Test client that sends the same anti-forgery header the real page sends."""

    def request(self, method, url, **kw):
        headers = dict(kw.pop("headers", None) or {})
        headers.setdefault("x-cashbook", "1")
        return super().request(method, url, headers=headers, **kw)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def new_client():
    c = Client(app)
    c.__enter__()
    return c


@pytest.fixture
def admin():
    c = new_client()
    r = c.post("/api/auth/setup", json={"full_name": "Gideon", "phone": "0712 000 001", "password": PW})
    assert r.status_code == 200, r.text
    c.me = r.json()["user"]
    return c


def make_user(admin_client, name, phone, role):
    r = admin_client.post("/api/users", json={"full_name": name, "phone": phone, "role": role, "password": PW})
    assert r.status_code == 200, r.text
    c = new_client()
    r = c.post("/api/auth/login", json={"phone": phone, "password": PW})
    assert r.status_code == 200, r.text
    c.me = r.json()["user"]
    return c


@pytest.fixture
def boss(admin):
    return make_user(admin, "Boss Director", "0712000009", "boss")


@pytest.fixture
def charles(admin):
    return make_user(admin, "Charles Mbugua Biaru", "0712000002", "manager")


@pytest.fixture
def erick(admin):
    return make_user(admin, "Erick Macharia", "0712000003", "manager")


def jpeg_bytes(w=400, h=300, color=(200, 220, 240)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def noisy_png(w=3000, h=2200):
    """A big, hard-to-compress phone-camera-sized photo (high-quality JPEG of noise)."""
    img = Image.effect_noise((w, h), 60).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()
