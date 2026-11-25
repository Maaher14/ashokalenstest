import io
import pytest
from PIL import Image
from lens import create_app
from lens.db import db


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "db.sqlite3"),
            "MEDIA_ROOT": str(tmp_path / "media"),
            "STORAGE": "local",
            "SECRET_KEY": "test-only-secret",
            "PRODUCTION": False,
            "DEMO_MODE": False,
        }
    )
    with app.app_context():
        db().executemany(
            "INSERT INTO users(id,sub,email,name) VALUES (?,?,?,?)",
            [(i, str(i), f"u{i}@ashoka.edu.in", f"User {i}") for i in range(1, 6)],
        )
    return app


@pytest.fixture
def client(app):
    return client_as(app, 1)


def client_as(app, user):
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = user
        s["csrf"] = "csrf"
    return client


def photo_bytes(size=(12, 8)):
    output = io.BytesIO()
    Image.new("RGB", size, (120, 180, 90)).save(output, "PNG")
    output.seek(0)
    return output


def create_post(client):
    return client.post("/api/posts", json={}, headers={"X-CSRF-Token": "csrf"}).json[
        "id"
    ]


def upload_photo(client, pid, revision=0):
    return client.post(
        f"/api/posts/{pid}/media",
        data={"revision": str(revision), "file": (photo_bytes(), "test.png")},
        headers={"X-CSRF-Token": "csrf"},
    )


def payload(upload, **extra):
    return {
        "revision": upload["revision"],
        "caption": "A campus moment",
        "location_id": 1,
        "audience": "all",
        "media": [{"id": upload["output"]["id"], "seconds": 3}],
        "publish": True,
    } | extra
