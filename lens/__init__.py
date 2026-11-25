import os
import secrets
from datetime import timedelta
from pathlib import Path
from flask import Flask, jsonify, request, session, g
from werkzeug.exceptions import HTTPException
from . import db


def create_app(config=None):
    root = Path(__file__).resolve().parent.parent
    data = Path(os.environ.get("LENS_DATA", str(root / "instance"))).resolve()
    data.mkdir(parents=True, exist_ok=True)
    key_path = data / "session.key"
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or key_path.read_text(),
        DATABASE=str(data / "lens.sqlite3"),
        MEDIA_ROOT=str(data / "media"),
        STORAGE=os.environ.get("STORAGE", "local"),
        S3_BUCKET=os.environ.get("S3_BUCKET", "ashoka-lens-media"),
        AWS_REGION=os.environ.get("AWS_REGION", "ap-southeast-2"),
        GOOGLE_CLIENT_ID=os.environ.get(
            "GOOGLE_CLIENT_ID",
            "176502342331-4ge9mjsg63u0mvrfic6bulrplrj5jdt9.apps.googleusercontent.com",
        ),
        DEMO_MODE=os.environ.get("DEMO_MODE") == "1",
        PRODUCTION=os.environ.get("PRODUCTION") == "1",
        MAX_CONTENT_LENGTH=21_000_000,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_REFRESH_EACH_REQUEST=False,
    )
    if config:
        app.config.update(config)
    if app.config["PRODUCTION"] and (
        app.config["DEMO_MODE"] or app.config["STORAGE"] != "s3"
    ):
        raise RuntimeError(
            "Production requires S3 storage and Google sign-in; demo login must be disabled."
        )
    app.config["SESSION_COOKIE_SECURE"] = app.config["PRODUCTION"]
    if app.config["STORAGE"] == "s3":
        import boto3
        from botocore.config import Config

        app.extensions["s3"] = boto3.client(
            "s3",
            region_name=app.config["AWS_REGION"],
            config=Config(
                connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}
            ),
        )
    app.teardown_appcontext(db.close)
    with app.app_context():
        db.initialise()
    from .routes import bp

    app.register_blueprint(bp)
    from .commands import register

    register(app)

    @app.before_request
    def security():
        g.user = db.one(
            "SELECT id,email,name,bio,approved FROM users WHERE id=?",
            (session.get("user_id"),),
        )
        if g.user and not g.user["approved"]:
            session.clear()
            g.user = None
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            token = request.headers.get("X-CSRF-Token", "")
            if not session.get("csrf") or not secrets.compare_digest(
                token, session["csrf"]
            ):
                return (
                    jsonify(
                        error="Your session changed. Refresh the page and try again."
                    ),
                    403,
                )

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = (
            "File is too large. Photos: 10 MB; audio: 20 MB."
            if error.code == 413
            else error.description
        )
        return jsonify(error=message), error.code

    from .processing import Invalid

    @app.errorhandler(Invalid)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(Exception)
    def failed(error):
        app.logger.exception("Request failed: %s", request.path)
        return (
            jsonify(
                error="The operation could not finish. Your last saved post is unchanged. Please retry."
            ),
            503,
        )

    return app
