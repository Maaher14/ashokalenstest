import json
import secrets
from functools import wraps
from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from .db import db, one, rows, transaction
from .policy import can_view, visibility
from . import posts, storage
from .processing import Invalid

bp = Blueprint("web", __name__)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not g.user:
            abort(401, description="Sign in with your Ashoka account to continue.")
        return fn(*args, **kwargs)

    return wrapped


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise Invalid("Send valid JSON settings.")
    return data


def page_number():
    try:
        return max(0, min(int(request.args.get("page", 0)), 100000))
    except ValueError:
        raise Invalid("Page must be a number.")


@bp.get("/")
def home():
    return redirect("/feed" if g.user else "/login")


@bp.get("/login")
def login():
    if g.user:
        return redirect("/feed")
    session["csrf"] = secrets.token_urlsafe(32)
    session["nonce"] = secrets.token_urlsafe(32)
    return render_template(
        "login.html",
        client_id=current_app.config["GOOGLE_CLIENT_ID"],
        demo=current_app.config["DEMO_MODE"],
    )


@bp.post("/auth/google")
def google_login():
    credential = body().get("credential")
    if not isinstance(credential, str) or len(credential) > 12000:
        raise Invalid("Google credential is missing or invalid.")
    try:
        claims = id_token.verify_oauth2_token(
            credential, Request(), current_app.config["GOOGLE_CLIENT_ID"]
        )
    except ValueError:
        abort(
            401, description="Google sign-in could not be verified. Please try again."
        )
    email = claims.get("email", "")
    if (
        claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
        or not session.get("nonce")
        or claims.get("nonce") != session["nonce"]
        or not claims.get("sub")
    ):
        abort(401, description="Sign-in attempt expired. Refresh and try again.")
    if (
        claims.get("email_verified") is not True
        or claims.get("hd") != "ashoka.edu.in"
        or not isinstance(email, str)
        or email.count("@") != 1
        or email.lower().split("@")[-1] != "ashoka.edu.in"
    ):
        abort(
            403, description="Please use your verified @ashoka.edu.in Google account."
        )
    email = email.lower()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO users(sub,email,name) VALUES (?,?,?) ON CONFLICT(sub) DO UPDATE SET email=excluded.email",
            (claims["sub"], email, str(claims.get("name") or email.split("@")[0])[:80]),
        )
        user = one("SELECT * FROM users WHERE sub=?", (claims["sub"],))
    if not user["approved"]:
        abort(
            403, description="Your access has been disabled. Contact the project team."
        )
    establish_session(user["id"])
    return jsonify(ok=True)


def establish_session(user_id):
    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["csrf"] = secrets.token_urlsafe(32)


@bp.post("/auth/demo")
def demo_login():
    if not current_app.config["DEMO_MODE"] or current_app.config["PRODUCTION"]:
        abort(404)
    email = body().get("email")
    user = one(
        "SELECT * FROM users WHERE email=? AND sub LIKE 'demo:%' AND approved=1",
        (email,),
    )
    if not user:
        abort(404, description="Run the seed-demo command first.")
    establish_session(user["id"])
    return jsonify(ok=True)


@bp.post("/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/feed")
@bp.get("/drafts")
@bp.get("/people")
@bp.get("/groups")
@bp.get("/profile/<int:ident>")
@bp.get("/post/<int:ident>")
@bp.get("/editor/<int:ident>")
def app_page(ident=None):
    if not g.user:
        return redirect("/login")
    session.setdefault("csrf", secrets.token_urlsafe(32))
    return render_template("app.html", user=g.user)


@bp.get("/api/me")
@login_required
def me():
    return jsonify(user=g.user, locations=rows("SELECT * FROM locations ORDER BY id"))


@bp.get("/api/feed")
@login_required
def feed():
    uid = g.user["id"]
    params = {"viewer": uid, "offset": page_number() * 20}
    where = visibility()
    if request.args.get("drafts") == "1":
        where = "p.owner_id=:viewer AND p.state='draft'"
    else:
        where += " AND p.state='published'"
    if request.args.get("following") == "1":
        where += " AND (p.owner_id=:viewer OR EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=:viewer AND f.followed_id=p.owner_id))"
    if owner := request.args.get("owner"):
        try:
            params["owner"] = int(owner)
        except ValueError:
            raise Invalid("Invalid profile.")
        where += " AND p.owner_id=:owner"
    ids = rows(
        f"SELECT p.id FROM posts p WHERE {where} ORDER BY p.created_at DESC,p.id DESC LIMIT 21 OFFSET :offset",
        params,
    )
    return jsonify(
        posts=[posts.detail(p["id"], uid) for p in ids[:20]], more=len(ids) > 20
    )


@bp.post("/api/posts")
@login_required
def create_post():
    ident = (
        db()
        .execute("INSERT INTO posts(owner_id) VALUES (?)", (g.user["id"],))
        .lastrowid
    )
    return jsonify(id=ident), 201


@bp.get("/api/posts/<int:ident>")
@login_required
def get_post(ident):
    if not can_view(g.user["id"], ident):
        abort(404, description="This post is unavailable or not shared with you.")
    return jsonify(posts.detail(ident, g.user["id"], request.args.get("edit") == "1"))


@bp.put("/api/posts/<int:ident>")
@login_required
def save_post(ident):
    return jsonify(posts.save(ident, g.user["id"], body()))


@bp.delete("/api/posts/<int:ident>")
@login_required
def delete_post(ident):
    posts.delete_post(ident, g.user["id"])
    return jsonify(ok=True)


@bp.post("/api/posts/<int:ident>/media")
@login_required
def upload(ident):
    posts.post_owned(ident, g.user["id"])
    file = request.files.get("file")
    if not file:
        raise Invalid("Choose a file to upload.")
    try:
        revision = int(request.form["revision"])
    except (KeyError, ValueError):
        raise Invalid("Post revision is missing. Reload the editor.")
    return jsonify(posts.upload(ident, g.user["id"], file, revision)), 201


@bp.post("/api/posts/<int:ident>/media/<int:source>/edits")
@login_required
def edit(ident, source):
    return jsonify(posts.edit(ident, source, g.user["id"], body()))


@bp.post("/api/posts/<int:ident>/jobs/<int:job>/retry")
@login_required
def retry(ident, job):
    posts.post_owned(ident, g.user["id"])
    item = one(
        "SELECT * FROM jobs WHERE id=? AND post_id=? AND state='Failed'", (job, ident)
    )
    if not item or not item["input_id"]:
        raise Invalid("No saved original to retry. Please upload the file again.")
    return jsonify(
        posts.edit(
            ident, item["input_id"], g.user["id"], json.loads(item["settings"]), job
        )
    )


def delivery(key, mime):
    try:
        file = storage.open_file(key)
    except FileNotFoundError:
        abort(404, description="Media unavailable.")
    file.seek(0, 2)
    length = file.tell()
    file.seek(0)
    response = send_file(file, mimetype=mime, conditional=False, etag=False, max_age=0)
    response.content_length = length
    response.make_conditional(request, accept_ranges=True, complete_length=length)
    response.call_on_close(file.close)
    return response


@bp.get("/api/posts/<int:ident>/media/<int:media_id>")
@login_required
def media_file(ident, media_id):
    media = one("SELECT * FROM media WHERE id=? AND post_id=?", (media_id, ident))
    if not media or not can_view(g.user["id"], ident, media):
        abort(404, description="Media unavailable or not shared with you.")
    return delivery(media["object_key"], json.loads(media["metadata"])["mime"])


@bp.get("/api/posts/<int:ident>/mix")
@login_required
def mix_file(ident):
    if not can_view(g.user["id"], ident):
        abort(404, description="Soundtrack unavailable.")
    post = one("SELECT mix_key FROM posts WHERE id=?", (ident,))
    if not post["mix_key"]:
        abort(404, description="No soundtrack attached.")
    return delivery(post["mix_key"], "audio/mpeg")


@bp.put("/api/posts/<int:ident>/like")
@bp.delete("/api/posts/<int:ident>/like")
@login_required
def like(ident):
    with transaction() as conn:
        if not can_view(g.user["id"], ident):
            abort(404, description="Post unavailable.")
        post = one("SELECT state FROM posts WHERE id=?", (ident,))
        if post["state"] != "published":
            raise Invalid("Publish this post before liking it.")
        if request.method == "PUT":
            conn.execute(
                "INSERT OR IGNORE INTO likes VALUES (?,?)", (g.user["id"], ident)
            )
        else:
            conn.execute(
                "DELETE FROM likes WHERE user_id=? AND post_id=?", (g.user["id"], ident)
            )
    return jsonify(
        likes=one("SELECT count(*) n FROM likes WHERE post_id=?", (ident,))["n"],
        liked=request.method == "PUT",
    )


@bp.get("/api/users")
@login_required
def users():
    query = request.args.get("q", "")[:80]
    return jsonify(
        users=rows(
            """SELECT u.id,u.name,u.email,u.bio,
      EXISTS(SELECT 1 FROM follows f WHERE f.followed_id=u.id AND f.follower_id=?) following
      FROM users u WHERE u.approved=1 AND (u.name LIKE ? OR u.email LIKE ?) ORDER BY u.name LIMIT 100""",
            (g.user["id"], f"%{query}%", f"%{query}%"),
        )
    )


@bp.get("/api/users/<int:ident>")
@login_required
def profile(ident):
    user = one(
        "SELECT id,name,email,bio FROM users WHERE id=? AND approved=1", (ident,)
    )
    if not user:
        abort(404, description="Profile unavailable.")
    user.update(
        followers=one("SELECT count(*) n FROM follows WHERE followed_id=?", (ident,))[
            "n"
        ],
        following_count=one(
            "SELECT count(*) n FROM follows WHERE follower_id=?", (ident,)
        )["n"],
        following=bool(
            one(
                "SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",
                (g.user["id"], ident),
            )
        ),
    )
    return jsonify(user)


@bp.put("/api/profile")
@login_required
def update_profile():
    data = body()
    name = data.get("name", "")
    bio = data.get("bio", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise Invalid("Display name must be 1–80 characters.")
    if not isinstance(bio, str) or len(bio) > 300:
        raise Invalid("Bio must be at most 300 characters.")
    db().execute(
        "UPDATE users SET name=?,bio=? WHERE id=?", (name.strip(), bio, g.user["id"])
    )
    return jsonify(ok=True)


@bp.put("/api/users/<int:ident>/follow")
@bp.delete("/api/users/<int:ident>/follow")
@login_required
def follow(ident):
    if ident == g.user["id"]:
        raise Invalid("You cannot follow yourself.")
    if not one("SELECT id FROM users WHERE id=? AND approved=1", (ident,)):
        abort(404, description="Profile unavailable.")
    if request.method == "PUT":
        db().execute(
            "INSERT OR IGNORE INTO follows VALUES (?,?)", (g.user["id"], ident)
        )
    else:
        db().execute(
            "DELETE FROM follows WHERE follower_id=? AND followed_id=?",
            (g.user["id"], ident),
        )
    return jsonify(ok=True)


@bp.get("/api/groups")
@login_required
def groups():
    result = rows(
        """SELECT g.*,u.name owner FROM groups g JOIN users u ON u.id=g.owner_id
       WHERE g.owner_id=? OR EXISTS(SELECT 1 FROM group_members gm WHERE gm.group_id=g.id AND gm.user_id=?) ORDER BY g.name""",
        (g.user["id"], g.user["id"]),
    )
    for group in result:
        group["members"] = rows(
            "SELECT u.id,u.name,u.email FROM users u JOIN group_members gm ON gm.user_id=u.id WHERE gm.group_id=? ORDER BY u.name",
            (group["id"],),
        )
    return jsonify(groups=result)


@bp.post("/api/groups")
@login_required
def create_group():
    name = body().get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise Invalid("Group name must be 1–60 characters.")
    with transaction() as conn:
        ident = conn.execute(
            "INSERT INTO groups(owner_id,name) VALUES (?,?)",
            (g.user["id"], name.strip()),
        ).lastrowid
        conn.execute("INSERT INTO group_members VALUES (?,?)", (ident, g.user["id"]))
    return jsonify(id=ident), 201


@bp.put("/api/groups/<int:ident>")
@login_required
def update_group(ident):
    data = body()
    with transaction() as conn:
        group = one(
            "SELECT * FROM groups WHERE id=? AND owner_id=?", (ident, g.user["id"])
        )
        if not group:
            abort(403, description="Only the group owner can change members.")
        emails = data.get("emails", [])
        if not isinstance(emails, list) or len(emails) > 200:
            raise Invalid("Choose up to 200 registered members.")
        members = {g.user["id"]}
        for email in emails:
            if not isinstance(email, str):
                raise Invalid("Enter a valid email.")
            user = one(
                "SELECT id FROM users WHERE lower(email)=? AND approved=1",
                (email.strip().lower(),),
            )
            if not user:
                raise Invalid(f"Member must sign in first: {email[:100]}")
            members.add(user["id"])
        conn.execute("DELETE FROM group_members WHERE group_id=?", (ident,))
        conn.executemany(
            "INSERT INTO group_members VALUES (?,?)", [(ident, u) for u in members]
        )
    return jsonify(ok=True)


@bp.delete("/api/groups/<int:ident>")
@login_required
def delete_group(ident):
    if not one(
        "SELECT id FROM groups WHERE id=? AND owner_id=?", (ident, g.user["id"])
    ):
        abort(403, description="Only the group owner can delete it.")
    db().execute("DELETE FROM groups WHERE id=?", (ident,))
    return jsonify(ok=True)


@bp.get("/health")
def health():
    db().execute("SELECT 1")
    return jsonify(status="ok")
