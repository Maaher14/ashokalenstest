"""Small operator commands. Sample accounts are local-only."""

import io
import json
import math
import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
import click
from PIL import Image, ImageDraw, ImageFont
from werkzeug.datastructures import FileStorage
from .db import db, one, transaction
from . import posts


def register(app):
    @app.cli.command("cleanup")
    def cleanup():
        """Retry removal of unreferenced objects."""
        posts.clean()
        click.echo("Cleanup pass complete.")

    @app.cli.command("recover")
    def recover():
        """Run once with web workers stopped, before service start."""
        db().execute(
            "UPDATE jobs SET state='Failed',reserved_bytes=0,error='Server restarted during processing. Retry saved original or re-upload.' WHERE state IN ('Receiving','Processing')"
        )
        posts.clean()
        click.echo("Interrupted jobs recovered.")

    @app.cli.command("set-access")
    @click.argument("email")
    @click.option("--approved", type=click.Choice(["yes", "no"]), required=True)
    def access(email, approved):
        """Enable/disable a registered account without altering its media."""
        result = db().execute(
            "UPDATE users SET approved=? WHERE lower(email)=?",
            (approved == "yes", email.lower()),
        )
        if not result.rowcount:
            raise click.ClickException("No registered account with that email.")
        click.echo("Access updated; subsequent requests use this status.")

    @app.cli.command("seed-demo")
    def demo():
        """Create illustrated sample posts in local demo mode only."""
        if (
            app.config["PRODUCTION"]
            or not app.config["DEMO_MODE"]
            or app.config["STORAGE"] != "local"
        ):
            raise click.ClickException(
                "Sample data requires DEMO_MODE=1, local storage and non-production mode."
            )
        if one("SELECT id FROM users WHERE sub LIKE 'demo:%'"):
            click.echo("Sample data already exists.")
            return
        for name, bio in [
            ("Maya Kapoor", "Collecting little moments between classes."),
            ("Arjun Mehta", "Music, late evenings and everything in between."),
            ("Tara Sen", "Looking for a different angle."),
        ]:
            first = name.split()[0].lower()
            db().execute(
                "INSERT INTO users(sub,email,name,bio) VALUES (?,?,?,?)",
                ("demo:" + first, first + "@ashoka.edu.in", name, bio),
            )
        maya = one("SELECT id FROM users WHERE sub='demo:maya'")["id"]
        arjun = one("SELECT id FROM users WHERE sub='demo:arjun'")["id"]
        tara = one("SELECT id FROM users WHERE sub='demo:tara'")["id"]
        db().execute("INSERT INTO follows VALUES (?,?)", (maya, arjun))
        group = (
            db()
            .execute(
                "INSERT INTO groups(owner_id,name) VALUES (?,?)",
                (maya, "The evening club"),
            )
            .lastrowid
        )
        db().executemany(
            "INSERT INTO group_members VALUES (?,?)", [(group, maya), (group, arjun)]
        )
        with TemporaryDirectory() as work:
            work = Path(work)
            for index, (owner, caption, location) in enumerate(
                [
                    (arjun, "The campus has a golden hour of its own.", 8),
                    (tara, "A quieter corner of a busy day.", 3),
                    (maya, "Some evenings deserve a soundtrack.", 1),
                    (arjun, "A little green between the deadlines.", 8),
                ]
            ):
                pid = (
                    db()
                    .execute("INSERT INTO posts(owner_id) VALUES (?)", (owner,))
                    .lastrowid
                )
                chosen = []
                revision = 0
                for pic in range(2 if index == 0 else 1):
                    image = work / "sample.jpg"
                    draw_sample(image, index + pic)
                    with image.open("rb") as f:
                        result = posts.upload(
                            pid,
                            owner,
                            FileStorage(f, filename="illustrated-campus.jpg"),
                            revision,
                        )
                    revision = result["revision"]
                    chosen.append({"id": result["output"]["id"], "seconds": 4})
                if index in (0, 2):
                    audio = work / "tone.wav"
                    sample_audio(audio)
                    with audio.open("rb") as f:
                        result = posts.upload(
                            pid,
                            owner,
                            FileStorage(f, filename="sample-sound.wav"),
                            revision,
                        )
                    revision = result["revision"]
                    chosen.append({"id": result["output"]["id"]})
                posts.save(
                    pid,
                    owner,
                    dict(
                        revision=revision,
                        caption=caption,
                        location_id=location,
                        audience="all",
                        media=chosen,
                        publish=True,
                    ),
                )
                db().execute("INSERT INTO likes VALUES (?,?)", (maya, pid))
        click.echo(
            "Created 3 fictional sample accounts and 4 illustrated posts. No real campus photographs or recordings used."
        )


def draw_sample(path, index):
    palettes = [
        ("#c1c9b6", "#d1b79a", "#997558", "#57705b"),
        ("#c9d5cf", "#c6b89a", "#8b7860", "#465e4b"),
        ("#ccbaa9", "#b27d61", "#7e5949", "#6c795f"),
        ("#b5c9b3", "#c1bc9b", "#8a9873", "#3b6054"),
    ]
    sky, stone, shadow, green = palettes[index % 4]
    im = Image.new("RGB", (1000, 800), sky)
    d = ImageDraw.Draw(im)
    d.ellipse((710, 40, 860, 190), fill="#efe3bb")
    d.rectangle((0, 530, 1000, 800), fill=green)
    if index % 4 == 3:
        for x, y, r in [(150, 310, 160), (470, 240, 210), (850, 330, 180)]:
            d.rectangle((x - 12, y, x + 12, 650), fill=shadow)
            d.ellipse((x - r, y - r, x + r, y + r), fill="#718d6d")
        d.polygon([(430, 800), (530, 520), (600, 520), (730, 800)], fill="#d1c7ac")
    else:
        d.rectangle((70, 220, 930, 610), fill=stone)
        d.rectangle((50, 195, 950, 235), fill=shadow)
        for x in range(120, 900, 160):
            d.rounded_rectangle((x, 290, x + 110, 575), radius=55, fill=shadow)
            d.rectangle((x, 350, x + 110, 575), fill=shadow)
        for y in range(635, 800, 30):
            d.rectangle((0, y, 1000, y + 10), fill=stone)
        d.rectangle((0, 600, 1000, 615), fill="#ddd1b5")
    d.rectangle((35, 35, 220, 66), fill="#f4f0e5")
    d.text((45, 43), "ILLUSTRATED SAMPLE", fill=green)
    im.save(path, "JPEG", quality=90)


def sample_audio(path, seconds=4):
    rate = 22050
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(
                        1300
                        * math.sin(2 * math.pi * 220 * i / rate)
                        * min(1, i / rate, (seconds - i / rate))
                    ),
                )
                for i in range(int(rate * seconds))
            )
        )
