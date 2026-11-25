import io
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
from lens.db import db, one, rows
from lens import posts
from lens.policy import can_view
from lens.processing import Invalid
from conftest import client_as, create_post, upload_photo, payload, photo_bytes

H = {"X-CSRF-Token": "csrf"}


def published(client, **extra):
    pid = create_post(client)
    up = upload_photo(client, pid).json
    assert (
        client.put(
            f"/api/posts/{pid}", json=payload(up, **extra), headers=H
        ).status_code
        == 200
    )
    return pid, up


def test_auth_and_csrf(app, client):
    assert app.test_client().get("/api/feed").status_code == 401
    assert client.post("/api/posts", json={}).status_code == 403
    assert client.get("/auth/demo").status_code == 405
    assert client.post("/auth/demo", json={}, headers=H).status_code == 404


@pytest.mark.parametrize(
    "change,code",
    [
        ({}, 200),
        ({"hd": None}, 403),
        ({"email": "personal@gmail.com"}, 403),
        ({"email": "x@ashoka.edu.in.attacker.com"}, 403),
        ({"email_verified": False}, 403),
        ({"nonce": "wrong"}, 401),
        ({"iss": "fake"}, 401),
    ],
)
def test_google_identity_checks(app, change, code):
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as s:
        csrf = s["csrf"]
        nonce = s["nonce"]
    claims = (
        dict(
            sub="real-sub",
            email="new@ashoka.edu.in",
            name="Campus User",
            hd="ashoka.edu.in",
            email_verified=True,
            nonce=nonce,
            iss="https://accounts.google.com",
        )
        | change
    )
    with patch(
        "lens.routes.id_token.verify_oauth2_token", return_value=claims
    ) as verify:
        r = c.post(
            "/auth/google",
            json={"credential": "signed-token"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == code
        assert verify.call_args.args[2] == app.config["GOOGLE_CLIENT_ID"]


def test_expired_or_forged_google_token(app):
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as s:
        csrf = s["csrf"]
    with patch(
        "lens.routes.id_token.verify_oauth2_token", side_effect=ValueError("expired")
    ):
        assert (
            c.post(
                "/auth/google",
                json={"credential": "bad"},
                headers={"X-CSRF-Token": csrf},
            ).status_code
            == 401
        )


@pytest.mark.parametrize(
    "audience,allowed",
    [
        ("all", {1, 2, 3, 4, 5}),
        ("followers", {1, 2}),
        ("selected", {1, 3}),
        ("groups", {1, 4}),
    ],
)
def test_permission_matrix_and_original_protection(app, client, audience, allowed):
    with app.app_context():
        db().execute("INSERT INTO follows VALUES (2,1)")
        group = (
            db()
            .execute("INSERT INTO groups(owner_id,name) VALUES (1,'Circle')")
            .lastrowid
        )
        db().execute("INSERT INTO group_members VALUES (?,4)", (group,))
    pid, up = published(
        client, audience=audience, emails=["u3@ashoka.edu.in"], group_ids=[group]
    )
    for uid in range(1, 6):
        c = client_as(app, uid)
        assert (c.get(f"/api/posts/{pid}").status_code == 200) == (uid in allowed)
        assert (len(c.get("/api/feed").json["posts"]) == 1) == (uid in allowed)
        assert (
            c.get(f'/api/posts/{pid}/media/{up["output"]["id"]}').status_code == 200
        ) == (uid in allowed)
        assert (
            c.get(f'/api/posts/{pid}/media/{up["original"]["id"]}').status_code == 200
        ) == (uid == 1)
        with app.app_context():
            assert can_view(uid, pid) == (uid in allowed)


@pytest.mark.parametrize(
    "audience,remove",
    [
        ("selected", "DELETE FROM post_viewers"),
        ("followers", "DELETE FROM follows"),
        ("groups", "DELETE FROM group_members"),
    ],
)
def test_revocation_rechecks_direct_urls(app, client, audience, remove):
    with app.app_context():
        db().execute("INSERT INTO follows VALUES (2,1)")
        group = (
            db()
            .execute("INSERT INTO groups(owner_id,name) VALUES (1,'Circle')")
            .lastrowid
        )
        db().execute("INSERT INTO group_members VALUES (?,2)", (group,))
    pid, up = published(
        client, audience=audience, emails=["u2@ashoka.edu.in"], group_ids=[group]
    )
    c = client_as(app, 2)
    url = f'/api/posts/{pid}/media/{up["output"]["id"]}'
    assert c.get(url).status_code == 200
    with app.app_context():
        db().execute(remove)
    with patch("lens.storage.open_file") as storage:
        assert c.get(url).status_code == 404
        storage.assert_not_called()
    assert c.get(f"/api/posts/{pid}").status_code == 404


def test_drafts_cross_post_and_unapproved_user(app, client):
    pid = create_post(client)
    up = upload_photo(client, pid).json
    assert client_as(app, 2).get(f"/api/posts/{pid}").status_code == 404
    other = create_post(client)
    assert (
        client.get(f'/api/posts/{other}/media/{up["output"]["id"]}').status_code == 404
    )
    with app.app_context():
        db().execute("UPDATE users SET approved=0 WHERE id=1")
    assert client.get("/api/feed").status_code == 401


def test_file_validation_and_image_count(client):
    pid = create_post(client)
    for i in range(10):
        r = upload_photo(client, pid, i)
        assert r.status_code == 201
    assert upload_photo(client, pid, 10).status_code == 400
    assert (
        client.post(
            f"/api/posts/{pid}/media",
            data={"revision": "10", "file": (io.BytesIO(b"fake"), "x.png")},
            headers=H,
        ).status_code
        == 400
    )


def test_100mb_boundary_and_reservations(app, client):
    pid = create_post(client)
    size = len(photo_bytes().getvalue())
    with app.app_context():
        # Model other admitted originals without allocating 100 MB of fixture bytes.
        db().execute(
            "INSERT INTO media(post_id,kind,object_key,bytes,filename,metadata) VALUES (?,'audio','fixture.wav',?,'fixture.wav','{}')",
            (pid, 100_000_000 - size),
        )
    assert upload_photo(client, pid).status_code == 201
    assert upload_photo(client, pid, 1).status_code == 400
    with app.app_context():
        db().execute("UPDATE media SET bytes=0 WHERE object_key='fixture.wav'")
        db().execute(
            "INSERT INTO jobs(post_id,kind,state,reserved_bytes) VALUES (?,'audio','Processing',100000000)",
            (pid,),
        )
    assert upload_photo(client, pid, 1).status_code == 400


def test_concurrent_uploads_cannot_exceed_count(app, client):
    pid = create_post(client)
    for i in range(9):
        assert upload_photo(client, pid, i).status_code == 201

    def send(_):
        return upload_photo(client_as(app, 1), pid, 9).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(send, [1, 2]))
    assert sorted(codes) in ([201, 400], [201, 409])
    with app.app_context():
        assert (
            one(
                "SELECT count(*) n FROM media WHERE post_id=? AND source_id IS NULL",
                (pid,),
            )["n"]
            == 10
        )


@pytest.mark.parametrize("seconds", [0, -1, 61, float("nan")])
def test_bad_timing_preserves_saved_post(app, client, seconds):
    pid, up = published(client)
    old = client.get(f"/api/posts/{pid}").json
    data = payload(
        up,
        revision=old["revision"],
        caption="Should not save",
        media=[{"id": up["output"]["id"], "seconds": seconds}],
    )
    assert client.put(f"/api/posts/{pid}", json=data, headers=H).status_code == 400
    assert client.get(f"/api/posts/{pid}").json["caption"] == old["caption"]


def test_stale_save_unknown_recipient_and_ownership(app, client):
    pid, up = published(client)
    assert (
        client.put(f"/api/posts/{pid}", json=payload(up), headers=H).status_code == 409
    )
    fresh = client.get(f"/api/posts/{pid}").json
    data = payload(
        up,
        revision=fresh["revision"],
        audience="selected",
        emails=["absent@ashoka.edu.in"],
    )
    assert client.put(f"/api/posts/{pid}", json=data, headers=H).status_code == 400
    c = client_as(app, 2)
    assert c.delete(f"/api/posts/{pid}", headers=H).status_code == 403
    assert (
        c.post(
            f'/api/posts/{pid}/media/{up["original"]["id"]}/edits', json={}, headers=H
        ).status_code
        == 403
    )


def test_edits_are_candidates_until_save(app, client):
    pid, up = published(client)
    r = client.post(
        f'/api/posts/{pid}/media/{up["original"]["id"]}/edits',
        json={"crop": [2, 1, 10, 7]},
        headers=H,
    )
    assert r.status_code == 200
    assert r.json["metadata"]["width"] == 8
    assert r.json["metadata"]["height"] == 6
    assert client.get(f"/api/posts/{pid}").json["media"][0]["id"] == up["output"]["id"]
    assert client_as(app, 2).get(r.json["url"]).status_code == 404
    bad = client.post(
        f'/api/posts/{pid}/media/{up["original"]["id"]}/edits',
        json={"crop": [0, 0, 999, 1]},
        headers=H,
    )
    assert bad.status_code == 400
    with app.app_context():
        assert one("SELECT count(*) n FROM jobs WHERE state='Failed'")["n"] == 1


def test_storage_failure_preserves_post_and_cleanup_retries(app, client):
    pid, up = published(client)
    with patch("lens.storage.put", side_effect=OSError("storage failure")):
        assert (
            client.post(
                f'/api/posts/{pid}/media/{up["original"]["id"]}/edits',
                json={},
                headers=H,
            ).status_code
            == 503
        )
    assert client.get(f"/api/posts/{pid}").json["media"][0]["id"] == up["output"]["id"]
    with patch("lens.storage.delete", side_effect=OSError("delete unavailable")):
        assert client.delete(f"/api/posts/{pid}", headers=H).status_code == 200
    assert client.get(f"/api/posts/{pid}").status_code == 404
    with app.app_context():
        assert rows("SELECT * FROM cleanup")
        posts.clean()
        assert rows("SELECT * FROM cleanup") == []


def test_failed_commit_does_not_change_caption(app, client):
    pid, up = published(client)
    fresh = client.get(f"/api/posts/{pid}").json
    from contextlib import contextmanager

    @contextmanager
    def broken_transaction():
        with transaction() as conn:
            yield conn
            raise OSError("simulated commit failure")

    with patch("lens.posts.transaction", broken_transaction):
        r = client.put(
            f"/api/posts/{pid}",
            json=payload(up, revision=fresh["revision"], caption="Lost update"),
            headers=H,
        )
        assert r.status_code == 503
    assert client.get(f"/api/posts/{pid}").json["caption"] == fresh["caption"]


def test_follows_likes_and_group_ownership(app, client):
    pid, up = published(client)
    for _ in range(2):
        assert client.put("/api/users/2/follow", headers=H).status_code == 200
        assert client.put(f"/api/posts/{pid}/like", headers=H).json["likes"] == 1
    assert client.put("/api/users/1/follow", headers=H).status_code == 400
    group = client.post("/api/groups", json={"name": "Club"}, headers=H).json["id"]
    assert (
        client.put(
            f"/api/groups/{group}", json={"emails": ["u2@ashoka.edu.in"]}, headers=H
        ).status_code
        == 200
    )
    assert (
        client_as(app, 2)
        .put(f"/api/groups/{group}", json={"emails": []}, headers=H)
        .status_code
        == 403
    )
    with app.app_context():
        assert one("SELECT count(*) n FROM follows")["n"] == 1


def test_filter_before_pagination_and_ties(app, client):
    with app.app_context():
        for _ in range(25):
            db().execute(
                "INSERT INTO posts(owner_id,state,audience,created_at) VALUES (1,'published','all','2026-01-01')"
            )
        for _ in range(5):
            db().execute(
                "INSERT INTO posts(owner_id,state,audience) VALUES (2,'published','selected')"
            )
    first = client.get("/api/feed").json
    second = client.get("/api/feed?page=1").json
    assert len(first["posts"]) == 20 and len(second["posts"]) == 5
    ids = [p["id"] for p in first["posts"] + second["posts"]]
    assert ids == list(range(25, 0, -1))


def test_restart_and_recover(app, client):
    pid, up = published(client)
    with app.app_context():
        db().execute(
            "INSERT INTO jobs(post_id,kind,state,reserved_bytes) VALUES (?,'image','Receiving',40)",
            (pid,),
        )
    result = app.test_cli_runner().invoke(args=["recover"])
    assert result.exit_code == 0
    with app.app_context():
        assert (
            one("SELECT reserved_bytes FROM jobs WHERE state='Failed'")[
                "reserved_bytes"
            ]
            == 0
        )
    assert client.get(f"/api/posts/{pid}").status_code == 200


def test_headers(app, client):
    pid, up = published(client)
    r = client.get(up["output"]["url"])
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_audio_limit_and_source_probe(client, tmp_path):
    from test_processing import tone

    pid = create_post(client)
    path = tmp_path / "tone.wav"
    tone(path, 1)
    for revision in range(3):
        with path.open("rb") as f:
            r = client.post(
                f"/api/posts/{pid}/media",
                data={"revision": str(revision), "file": (f, "tone.wav")},
                headers=H,
            )
        assert r.status_code == 201
    with path.open("rb") as f:
        assert (
            client.post(
                f"/api/posts/{pid}/media",
                data={"revision": "3", "file": (f, "tone.wav")},
                headers=H,
            ).status_code
            == 400
        )
    other = create_post(client)
    assert (
        client.post(
            f"/api/posts/{other}/media",
            data={
                "revision": "0",
                "file": (io.BytesIO(b"x" * 10_000_001), "large.png"),
            },
            headers=H,
        ).status_code
        == 400
    )


def test_actual_mixed_post_and_failed_replacement(app, client, tmp_path):
    from test_processing import tone

    pid = create_post(client)
    up = upload_photo(client, pid).json
    path = tmp_path / "tone.wav"
    tone(path, 4)
    with path.open("rb") as f:
        audio = client.post(
            f"/api/posts/{pid}/media",
            data={"revision": str(up["revision"]), "file": (f, "tone.wav")},
            headers=H,
        ).json
    data = payload(
        up,
        revision=audio["revision"],
        media=[{"id": up["output"]["id"], "seconds": 8}, {"id": audio["output"]["id"]}],
    )
    saved = client.put(f"/api/posts/{pid}", json=data, headers=H)
    assert saved.status_code == 200
    assert client_as(app, 2).get(saved.json["mix_url"]).status_code == 200
    old = client.get(f"/api/posts/{pid}").json
    data["revision"] = old["revision"]
    data["caption"] = "Must not replace"
    with patch("lens.posts.mix_audio", side_effect=Invalid("Processing timeout")):
        assert client.put(f"/api/posts/{pid}", json=data, headers=H).status_code == 400
    assert client.get(f"/api/posts/{pid}").json["caption"] == old["caption"]
    assert client_as(app, 2).get(old["mix_url"]).status_code == 200
    with app.app_context():
        assert (
            one("SELECT count(*) n FROM jobs WHERE kind='mix' AND state='Failed'")["n"]
            == 1
        )


def test_following_profile_edit_and_empty_selected_audience(app, client):
    pid, up = published(client, audience="selected", emails=[])
    assert client_as(app, 2).get("/api/feed").json["posts"] == []
    assert (
        client.put(
            "/api/profile", json={"name": "New Name", "bio": "Campus"}, headers=H
        ).status_code
        == 200
    )
    assert client.get("/api/users/1").json["name"] == "New Name"
    assert client_as(app, 2).get("/api/feed?following=1").json["posts"] == []
    assert client.get("/api/feed?owner=1").json["posts"][0]["id"] == pid


def test_production_cannot_enable_demo_or_local_storage(tmp_path):
    from lens import create_app

    with pytest.raises(RuntimeError):
        create_app({"PRODUCTION": True, "DEMO_MODE": True, "STORAGE": "local"})


def test_authorised_range_request_rechecks_access(app, client):
    pid, up = published(client, audience="selected", emails=["u2@ashoka.edu.in"])
    c = client_as(app, 2)
    url = up["output"]["url"]
    response = c.get(url, headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert len(response.data) == 10
    assert response.headers["Content-Range"].startswith("bytes 0-9/")
    with app.app_context():
        db().execute("DELETE FROM post_viewers WHERE post_id=?", (pid,))
    assert c.get(url, headers={"Range": "bytes=0-9"}).status_code == 404


def test_page_bootstrap_json_survives_html_attribute_escaping(client):
    from html.parser import HTMLParser
    class BodyParser(HTMLParser):
        data=None
        def handle_starttag(self,tag,attrs):
            if tag=='body':self.data=dict(attrs)['data-user']
    parser=BodyParser();parser.feed(client.get('/feed').get_data(as_text=True))
    assert json.loads(parser.data)['id']==1
