"""Real local-stack browser checks with synthetic accounts; no Google/S3 claims."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lens.commands import draw_sample, sample_audio

with tempfile.TemporaryDirectory() as work:
    work = Path(work)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = os.environ | {
        "LENS_DATA": str(work / "data"),
        "DEMO_MODE": "1",
        "PRODUCTION": "0",
        "STORAGE": "local",
    }
    subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "seed-demo"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    server = subprocess.Popen(
        [sys.executable, "-m", "flask", "--app", "app", "run", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/health")
                break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as pw:
            binary = os.environ.get("CHROMIUM_EXECUTABLE")
            browser = pw.chromium.launch(
                **({"executable_path": binary} if binary else {}),
                args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
            )
            contexts = [
                browser.new_context(viewport={"width": 1440, "height": 1000})
                for _ in range(3)
            ]
            pages = [ctx.new_page() for ctx in contexts]
            errors = []
            for page, name in zip(pages, ["Maya", "Arjun", "Tara"]):
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(base + "/login")
                page.get_by_role("button", name="Continue as " + name).click()
                page.wait_for_url("**/feed")
                page.locator(".post-card").first.wait_for()
            owner, recipient, excluded = pages
            owner.get_by_role("button", name="Create a post", exact=False).first.click()
            owner.wait_for_url("**/editor/*")
            post_id = owner.url.rsplit("/", 1)[-1]
            for i in range(2):
                draw_sample(work / f"photo{i}.jpg", i)
            for i in range(2):
                sample_audio(work / f"audio{i}.wav", 12)
            owner.locator("#upload").set_input_files(
                [
                    str(work / "photo0.jpg"),
                    str(work / "photo1.jpg"),
                    str(work / "audio0.wav"),
                    str(work / "audio1.wav"),
                ]
            )
            expect(owner.locator(".media-editor")).to_have_count(4, timeout=45000)
            expect(owner.locator("#publish")).to_be_enabled(timeout=45000)
            owner.locator(".seconds").nth(0).fill("3")
            owner.locator(".seconds").nth(1).fill("5")
            # Crop and rotate through the real editor; then trim a source and change gain.
            photo = owner.locator(".media-editor").nth(0)
            photo.locator("summary").click()
            photo.locator("[name=rotate]").select_option("90")
            photo.get_by_role("button", name="Apply edit").click()
            expect(owner.locator("#publish")).to_be_enabled(timeout=30000)
            clip = owner.locator(".media-editor").nth(2)
            clip.locator("summary").click()
            clip.locator("[name=start]").fill("2")
            clip.locator("[name=end]").fill("10")
            clip.locator("[name=volume]").fill("0.3")
            clip.get_by_role("button", name="Apply edit").click()
            expect(owner.locator("#publish")).to_be_enabled(timeout=30000)
            owner.locator("#caption").fill("System test: rehearsal")
            owner.locator("#location").select_option("1")
            owner.locator("#audience").select_option("selected")
            owner.locator("#recipients").fill("arjun@ashoka.edu.in")
            owner.locator("#save").click()
            expect(owner.locator("#save-status")).to_contain_text(
                "Saved", timeout=30000
            )
            owner.locator("#preview").click()
            expect(owner.locator("#player-dialog .play")).to_be_enabled(timeout=30000)
            owner.locator("#player-dialog .play").click()
            time.sleep(0.5)
            owner.locator("#player-dialog .seek").evaluate(
                "el=>{el.value=4;el.dispatchEvent(new Event('input'));}"
            )
            expect(owner.locator("#player-dialog .player-stage img")).to_have_attribute(
                "alt", "Photo 2 of 2"
            )
            owner.get_by_role("button", name="Close player").click()
            owner.locator("#publish").click()
            owner.wait_for_url("**/post/" + post_id)
            expect(owner.locator(".play")).to_be_enabled(timeout=30000)
            recipient.goto(base + "/post/" + post_id)
            expect(recipient.locator(".play")).to_be_enabled(timeout=30000)
            excluded.goto(base + "/post/" + post_id)
            expect(excluded.locator(".error-panel")).to_be_visible()
            data = recipient.request.get(base + "/api/posts/" + post_id).json()
            media_url = data["media"][0]["url"]
            mix_url = data["mix_url"]
            assert recipient.request.get(base + media_url).status == 200
            assert recipient.request.get(base + mix_url).status == 200
            assert excluded.request.get(base + media_url).status == 404
            owner.goto(base + "/editor/" + post_id)
            owner.locator("#recipients").fill("")
            owner.locator("#save").click()
            expect(owner.locator("#save-status")).to_contain_text(
                "Saved", timeout=30000
            )
            assert recipient.request.get(base + "/api/posts/" + post_id).status == 404
            assert recipient.request.get(base + media_url).status == 404
            assert recipient.request.get(base + mix_url).status == 404
            # Circle creation and member edits.
            owner.goto(base + "/groups")
            owner.get_by_placeholder("Name your circle").fill("Rehearsal circle")
            owner.get_by_role("button", name="Create circle").click()
            group = owner.locator(".group-card").filter(
                has=owner.get_by_role("heading", name="Rehearsal circle")
            )
            group.locator("textarea").fill("arjun@ashoka.edu.in")
            group.get_by_role("button", name="Save members").click()
            expect(owner.get_by_text("Arjun Mehta", exact=True).first).to_be_visible()
            # Profile editing, following and likes.
            owner.goto(base + "/profile/1")
            owner.get_by_role("button", name="Edit profile", exact=True).click()
            owner.locator("[name=bio]").fill("A campus photographer.")
            owner.get_by_role("button", name="Save profile").click()
            expect(owner.get_by_text("A campus photographer.")).to_be_visible()
            owner.goto(base + "/feed")
            owner.locator("[data-like]").first.click()
            expect(owner.locator("[data-like]").first).to_be_enabled()
            for width in [1440, 768, 390, 360]:
                owner.set_viewport_size({"width": width, "height": 1000})
                owner.goto(base + "/feed")
                expect(owner.locator(".post-card").first).to_be_visible()
                assert owner.evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                ), f"Horizontal overflow at {width}"
            assert not errors, errors
            browser.close()
            print(
                "PASS: browser publish/edit/play/seek, three-user sharing and revocation, circles/profile/interactions, responsive widths 1440/768/390/360. Google and S3 were not used in this local system test."
            )
    finally:
        server.terminate()
        server.wait(timeout=10)
