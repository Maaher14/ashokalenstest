"""Post lifecycle: prepare objects, atomically commit references, clean unused files."""

import json
import uuid
import threading
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from flask import abort
from .db import db, one, rows, transaction
from . import storage
from .processing import Invalid, number, inspect, image_edit, audio_edit, mix_audio

# One process with threaded requests on EC2. Serialize expensive mutations to
# bound RAM and prevent cleanup from racing an in-flight object write.
_media_lock = threading.RLock()


def serial_media(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _media_lock:
            return fn(*args, **kwargs)

    return wrapped


MAX_TOTAL = 100_000_000
LIMITS = {"image": (10, 10_000_000), "audio": (3, 20_000_000)}


def post_owned(post_id, user_id):
    post = one("SELECT * FROM posts WHERE id=? AND state!='deleted'", (post_id,))
    if not post:
        abort(404, description="Post unavailable.")
    if post["owner_id"] != user_id:
        abort(403, description="Only the owner can change this post.")
    return post


def check_revision(post, expected):
    if expected != post["revision"]:
        abort(
            409,
            description="This post changed in another window. Reload before saving.",
        )


def queue_key(post_id, suffix):
    key = f"posts/{post_id}/{uuid.uuid4().hex}{suffix}"
    db().execute("INSERT INTO cleanup(object_key,post_id) VALUES (?,?)", (key, post_id))
    return key


@serial_media
def clean():
    for item in rows("SELECT * FROM cleanup LIMIT 100"):
        key = item["object_key"]
        if one("SELECT 1 FROM media WHERE object_key=?", (key,)) or one(
            "SELECT 1 FROM posts WHERE mix_key=?", (key,)
        ):
            db().execute("DELETE FROM cleanup WHERE object_key=?", (key,))
            continue
        if one(
            "SELECT 1 FROM jobs WHERE post_id=? AND state IN ('Receiving','Processing')",
            (item["post_id"],),
        ):
            continue
        try:
            storage.delete(key)
            db().execute("DELETE FROM cleanup WHERE object_key=?", (key,))
        except Exception:
            db().execute(
                "UPDATE cleanup SET attempts=attempts+1,last_error='Storage deletion failed' WHERE object_key=?",
                (key,),
            )


def media_record(row):
    item = dict(row)
    item.pop("object_key", None)
    item["metadata"] = json.loads(item["metadata"])
    item["settings"] = json.loads(item["settings"])
    item["url"] = f"/api/posts/{item['post_id']}/media/{item['id']}"
    return item


def detail(post_id, viewer, editing=False):
    post = one(
        "SELECT p.*,u.name author,u.email author_email FROM posts p JOIN users u ON u.id=p.owner_id WHERE p.id=?",
        (post_id,),
    )
    post.pop("mix_key", None)
    post["media"] = [
        media_record(m)
        for m in rows(
            "SELECT * FROM media WHERE post_id=? AND active=1 ORDER BY kind,position,id",
            (post_id,),
        )
    ]
    post["likes"] = one("SELECT count(*) n FROM likes WHERE post_id=?", (post_id,))["n"]
    post["liked"] = bool(
        one("SELECT 1 FROM likes WHERE post_id=? AND user_id=?", (post_id, viewer))
    )
    post["location"] = one(
        "SELECT name FROM locations WHERE id=?", (post["location_id"],)
    )
    post["location"] = post["location"]["name"] if post["location"] else ""
    post["mix_url"] = (
        f"/api/posts/{post_id}/mix"
        if one("SELECT mix_key FROM posts WHERE id=?", (post_id,))["mix_key"]
        else None
    )
    if editing and viewer == post["owner_id"]:
        post["originals"] = [
            media_record(m)
            for m in rows(
                "SELECT * FROM media WHERE post_id=? AND source_id IS NULL ORDER BY id",
                (post_id,),
            )
        ]
        post["candidates"] = [
            media_record(m)
            for m in rows(
                "SELECT * FROM media WHERE post_id=? AND source_id IS NOT NULL ORDER BY id",
                (post_id,),
            )
        ]
        post["viewers"] = rows(
            "SELECT u.id,u.email,u.name FROM post_viewers pv JOIN users u ON u.id=pv.user_id WHERE pv.post_id=?",
            (post_id,),
        )
        post["group_ids"] = [
            r["group_id"]
            for r in rows(
                "SELECT group_id FROM post_groups WHERE post_id=?", (post_id,)
            )
        ]
        post["jobs"] = rows(
            "SELECT id,input_id,kind,state,error,attempts FROM jobs WHERE post_id=? ORDER BY id DESC LIMIT 10",
            (post_id,),
        )
        post["upload_bytes"] = sum(m["bytes"] for m in post["originals"])
    return post


@serial_media
def upload(post_id, user_id, file, expected):
    suffix = Path(file.filename or "").suffix.lower()
    kind = (
        "image"
        if suffix in (".jpg", ".jpeg", ".png")
        else "audio" if suffix in (".mp3", ".wav") else None
    )
    if not kind:
        raise Invalid("Choose JPEG, PNG, MP3 or WAV files.")
    cap, byte_limit = LIMITS[kind]
    with TemporaryDirectory() as work:
        source = Path(work) / ("original" + suffix)
        size = 0
        with source.open("wb") as out:
            while chunk := file.stream.read(64 * 1024):
                size += len(chunk)
                if size > byte_limit:
                    raise Invalid(
                        f"{kind.title()} file exceeds {byte_limit//1_000_000} MB."
                    )
                out.write(chunk)
        if not size:
            raise Invalid("The file is empty.")
        with transaction() as conn:
            check_revision(post_owned(post_id, user_id), expected)
            count = one(
                "SELECT count(*) n,coalesce(sum(bytes),0) b FROM media WHERE post_id=? AND source_id IS NULL AND kind=?",
                (post_id, kind),
            )
            busy = one(
                "SELECT count(*) n FROM jobs WHERE post_id=? AND kind=? AND reserved_bytes>0 AND state IN ('Receiving','Processing')",
                (post_id, kind),
            )
            total = one(
                "SELECT coalesce(sum(bytes),0) n FROM media WHERE post_id=? AND source_id IS NULL",
                (post_id,),
            )["n"]
            reserved = one(
                "SELECT coalesce(sum(reserved_bytes),0) n FROM jobs WHERE post_id=? AND state IN ('Receiving','Processing')",
                (post_id,),
            )["n"]
            if count["n"] + busy["n"] >= cap:
                raise Invalid(
                    f'A post allows up to {cap} {"photos" if kind=="image" else "audio clips"}, including preserved originals.'
                )
            if total + reserved + size > MAX_TOTAL:
                raise Invalid("Total original uploads exceed 100 MB.")
            job = conn.execute(
                "INSERT INTO jobs(post_id,kind,state,reserved_bytes) VALUES (?,?,'Receiving',?)",
                (post_id, kind, size),
            ).lastrowid
        try:
            metadata = inspect(source, kind)
            db().execute("UPDATE jobs SET state='Processing' WHERE id=?", (job,))
            original_key = queue_key(post_id, suffix)
            storage.put(source, original_key, metadata["mime"])
            with transaction() as conn:
                post_owned(post_id, user_id)
                original = conn.execute(
                    "INSERT INTO media(post_id,kind,object_key,bytes,filename,metadata) VALUES (?,?,?,?,?,?)",
                    (
                        post_id,
                        kind,
                        original_key,
                        size,
                        Path(file.filename).name[:160],
                        json.dumps(metadata),
                    ),
                ).lastrowid
                conn.execute("DELETE FROM cleanup WHERE object_key=?", (original_key,))
                conn.execute(
                    "UPDATE jobs SET input_id=?,reserved_bytes=0 WHERE id=?",
                    (original, job),
                )
            output = _prepare_edit(post_id, original, source, kind, metadata, {}, work)
            with transaction() as conn:
                conn.execute("UPDATE jobs SET state='Ready' WHERE id=?", (job,))
                conn.execute(
                    "UPDATE posts SET revision=revision+1 WHERE id=?", (post_id,)
                )
            return {
                "original": media_record(
                    one("SELECT * FROM media WHERE id=?", (original,))
                ),
                "output": media_record(output),
                "revision": one("SELECT revision FROM posts WHERE id=?", (post_id,))[
                    "revision"
                ],
            }
        except BaseException:
            db().execute(
                "UPDATE jobs SET state='Failed',reserved_bytes=0,error='Upload or processing failed. Retry the saved original or upload again.' WHERE id=?",
                (job,),
            )
            clean()
            raise


def _prepare_edit(post_id, original, source, kind, metadata, settings, work):
    out = Path(work) / ("edited.jpg" if kind == "image" else "edited.mp3")
    meta = (
        image_edit(source, out, settings)
        if kind == "image"
        else audio_edit(source, out, settings, metadata)
    )
    key = queue_key(post_id, out.suffix)
    storage.put(out, key, meta["mime"])
    with transaction() as conn:
        post = one("SELECT state FROM posts WHERE id=?", (post_id,))
        if post["state"] == "deleted":
            abort(409, description="This post was deleted.")
        ident = conn.execute(
            "INSERT INTO media(post_id,source_id,kind,object_key,bytes,filename,metadata,settings) VALUES (?,?,?,?,?,?,?,?)",
            (
                post_id,
                original,
                kind,
                key,
                out.stat().st_size,
                out.name,
                json.dumps(meta),
                json.dumps(settings),
            ),
        ).lastrowid
        conn.execute("DELETE FROM cleanup WHERE object_key=?", (key,))
    return one("SELECT * FROM media WHERE id=?", (ident,))


@serial_media
def edit(post_id, source_id, user_id, settings, retry_job=None):
    post_owned(post_id, user_id)
    original = one(
        "SELECT * FROM media WHERE id=? AND post_id=? AND source_id IS NULL",
        (source_id, post_id),
    )
    if not original:
        abort(404, description="Original file unavailable.")
    if not isinstance(settings, dict):
        raise Invalid("Edit settings must be an object.")
    if retry_job:
        job = retry_job
        db().execute(
            "UPDATE jobs SET state='Processing',attempts=attempts+1,error=NULL WHERE id=?",
            (job,),
        )
    else:
        job = (
            db()
            .execute(
                "INSERT INTO jobs(post_id,input_id,kind,state,settings) VALUES (?,?,?,'Processing',?)",
                (post_id, source_id, original["kind"], json.dumps(settings)),
            )
            .lastrowid
        )
    try:
        with TemporaryDirectory() as work:
            path = Path(work) / "source"
            storage.download(original["object_key"], path)
            output = _prepare_edit(
                post_id,
                source_id,
                path,
                original["kind"],
                json.loads(original["metadata"]),
                settings,
                work,
            )
        db().execute("UPDATE jobs SET state='Ready' WHERE id=?", (job,))
        return media_record(output)
    except BaseException:
        db().execute(
            "UPDATE jobs SET state='Failed',error='Processing failed. Check settings and retry.' WHERE id=?",
            (job,),
        )
        clean()
        raise


@serial_media
def save(post_id, user_id, data):
    post = post_owned(post_id, user_id)
    check_revision(post, data.get("revision"))
    caption = data.get("caption", "")
    if not isinstance(caption, str) or len(caption) > 1000:
        raise Invalid("Caption must be at most 1,000 characters.")
    location = data.get("location_id") or None
    if location is not None and not one(
        "SELECT id FROM locations WHERE id=?", (location,)
    ):
        raise Invalid("Choose a campus location from the list.")
    audience = data.get("audience", "all")
    if audience not in ("all", "followers", "groups", "selected"):
        raise Invalid("Choose a valid audience.")
    viewers = []
    groups = []
    if audience == "selected":
        emails = data.get("emails", [])
        if not isinstance(emails, list) or len(emails) > 200:
            raise Invalid("Enter up to 200 registered recipients.")
        for email in emails:
            if not isinstance(email, str):
                raise Invalid("Recipient email is invalid.")
            user = one(
                "SELECT id FROM users WHERE lower(email)=? AND approved=1",
                (email.strip().lower(),),
            )
            if not user:
                raise Invalid(f"Recipient must sign in first: {email[:100]}")
            viewers.append(user["id"])
    if audience == "groups":
        groups = data.get("group_ids", [])
        if not isinstance(groups, list) or len(groups) > 100:
            raise Invalid("Choose valid groups.")
        for group in groups:
            if not isinstance(group, int) or not one(
                "SELECT id FROM groups WHERE id=? AND owner_id=?", (group, user_id)
            ):
                raise Invalid("You can share with groups you own.")
    selection = data.get("media", [])
    if not isinstance(selection, list) or len(selection) > 13:
        raise Invalid("Select up to 10 photos and 3 audio clips.")
    selected = []
    seen = set()
    images = 0
    audio = 0
    length = 0
    for item in selection:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise Invalid("Invalid media selection.")
        row = one(
            "SELECT * FROM media WHERE id=? AND post_id=? AND source_id IS NOT NULL",
            (item["id"], post_id),
        )
        if not row or row["source_id"] in seen:
            raise Invalid("Choose one edited version per original file from this post.")
        seen.add(row["source_id"])
        seconds = (
            number(item.get("seconds", 5), "Photo duration", 0.1, 60)
            if row["kind"] == "image"
            else 0
        )
        images += row["kind"] == "image"
        audio += row["kind"] == "audio"
        length += seconds
        selected.append((row, seconds))
    if images > 10 or audio > 3 or length > 60.000001:
        raise Invalid("Use up to 10 photos, 3 audio clips and 60 seconds total.")
    publish = data.get("publish", False)
    if not isinstance(publish, bool):
        raise Invalid("Publication flag is invalid.")
    # A published post stays published when edited; removing every image is invalid.
    if (publish or post["state"] == "published") and not images:
        raise Invalid("Add at least one photo before publishing.")
    mix_key = None
    mix_job = None
    committed = False
    try:
        tracks = [m for m, _ in selected if m["kind"] == "audio"]
        if tracks and length:
            mix_job = (
                db()
                .execute(
                    "INSERT INTO jobs(post_id,kind,state,settings) VALUES (?,'mix','Processing',?)",
                    (post_id, json.dumps({"seconds": length})),
                )
                .lastrowid
            )
            with TemporaryDirectory() as work:
                paths = []
                for i, track in enumerate(tracks):
                    path = Path(work) / f"{i}.mp3"
                    storage.download(track["object_key"], path)
                    paths.append(path)
                out = Path(work) / "mix.mp3"
                mix_audio(paths, out, length)
                mix_key = queue_key(post_id, ".mp3")
                db().execute(
                    "UPDATE jobs SET output_key=? WHERE id=?", (mix_key, mix_job)
                )
                storage.put(out, mix_key, "audio/mpeg")
        with transaction() as conn:
            check_revision(post_owned(post_id, user_id), data.get("revision"))
            conn.execute("UPDATE media SET active=0 WHERE post_id=?", (post_id,))
            positions = {"image": 0, "audio": 0}
            for m, seconds in selected:
                positions[m["kind"]] += 1
                conn.execute(
                    "UPDATE media SET active=1,position=?,seconds=? WHERE id=?",
                    (positions[m["kind"]], seconds, m["id"]),
                )
            for unused in rows(
                "SELECT object_key FROM media WHERE post_id=? AND source_id IS NOT NULL AND active=0",
                (post_id,),
            ):
                conn.execute(
                    "INSERT OR IGNORE INTO cleanup(object_key,post_id) VALUES (?,?)",
                    (unused["object_key"], post_id),
                )
            conn.execute(
                "DELETE FROM media WHERE post_id=? AND source_id IS NOT NULL AND active=0",
                (post_id,),
            )
            conn.execute("DELETE FROM post_viewers WHERE post_id=?", (post_id,))
            conn.execute("DELETE FROM post_groups WHERE post_id=?", (post_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO post_viewers VALUES (?,?)",
                [(post_id, v) for v in viewers],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO post_groups VALUES (?,?)",
                [(post_id, v) for v in groups],
            )
            conn.execute(
                "UPDATE posts SET caption=?,location_id=?,audience=?,mix_key=?,state=?,revision=revision+1 WHERE id=?",
                (
                    caption,
                    location,
                    audience,
                    mix_key,
                    "published" if publish or post["state"] == "published" else "draft",
                    post_id,
                ),
            )
            if mix_key:
                conn.execute("DELETE FROM cleanup WHERE object_key=?", (mix_key,))
            if post["mix_key"]:
                conn.execute(
                    "INSERT OR IGNORE INTO cleanup(object_key,post_id) VALUES (?,?)",
                    (post["mix_key"], post_id),
                )
        committed = True
        if mix_job:
            db().execute("UPDATE jobs SET state='Ready' WHERE id=?", (mix_job,))
        return detail(post_id, user_id, True)
    finally:
        if mix_job and not committed:
            db().execute(
                "UPDATE jobs SET state='Failed',error='Soundtrack save failed. Save the composition again to retry.' WHERE id=?",
                (mix_job,),
            )
        clean()


@serial_media
def delete_post(post_id, user_id):
    with transaction() as conn:
        post = post_owned(post_id, user_id)
        conn.execute(
            "UPDATE posts SET state='deleted',mix_key=NULL,revision=revision+1 WHERE id=?",
            (post_id,),
        )
        for m in rows("SELECT object_key FROM media WHERE post_id=?", (post_id,)):
            conn.execute(
                "INSERT OR IGNORE INTO cleanup(object_key,post_id) VALUES (?,?)",
                (m["object_key"], post_id),
            )
        if post["mix_key"]:
            conn.execute(
                "INSERT OR IGNORE INTO cleanup(object_key,post_id) VALUES (?,?)",
                (post["mix_key"], post_id),
            )
        conn.execute("DELETE FROM jobs WHERE post_id=?", (post_id,))
        conn.execute("DELETE FROM media WHERE post_id=?", (post_id,))
    clean()
