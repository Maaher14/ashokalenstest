# Ashoka Lens

A campus photo and audio sharing app. Create timed slideshows, edit photos and audio, and share with campus members, followers, your circles or selected people. Flask, SQLite, plain JavaScript, Pillow, FFmpeg and private S3.

## Run locally

Python 3.12+ and FFmpeg/ffprobe are required. On macOS install FFmpeg with `brew install ffmpeg`; on Ubuntu use `sudo apt install ffmpeg python3-venv`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open **http://localhost:5001**. Google login needs this origin registered for your Client ID. The configured Client ID is public, not a secret. `.env.example` lists configuration variables; export them in your shell or use the deployment environment file. Source code does not auto-load `.env`.

Local execution stores files under `instance/`. The cloud deployment uses S3; media bytes never go in SQLite.

### Local sample mode

```bash
export DEMO_MODE=1
flask --app app seed-demo
python app.py
```

The sign-in page then offers three fictional sample accounts with four illustrated posts and generated tones. Sample mode cannot run with `PRODUCTION=1`. It is for local testing only; the deployed app uses Google. Do not upload private material into a sample-mode server.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/timeline.test.mjs
```

Browser system checks: `python -m playwright install chromium`, then `python tests/browser_system.py`. These start a separate local server and create temporary synthetic data. See [testing](docs/TESTING.md) for what is actually tested and the hosted checks still required.

## Deploy to EC2

From the Ubuntu host, clone this repository into a separate code directory:

```bash
git clone https://github.com/Maaher14/ashokalenstest.git ~/ashoka-lens-code
cd ~/ashoka-lens-code
sudo bash deploy/install.sh
```

The installer runs Gunicorn under systemd, configures Nginx, and preserves configuration and data outside the checkout. S3 access uses the EC2 IAM role, with no permanent AWS keys. The old foreground sign-in test may be stopped with Ctrl+C; the full app uses port 8001.

The existing distribution's HTTPS address is **https://d3qkghr7scdsnb.cloudfront.net**. This repository does not deploy itself; the running site changes only after installation/update on EC2.

CloudFront must use the EC2 public DNS as its origin, HTTP port 80, HTTPS redirect for viewers, all seven HTTP methods, `CachingDisabled`, `AllViewer`, and a 120-second response timeout. Do not use S3 as a public origin. Google must allow the exact CloudFront HTTPS origin. [Deployment details](docs/DEPLOYMENT.md).

## Project layout

- `lens/routes.py`: accounts, feed, posts, groups and authorised file delivery.
- `lens/posts.py`: uploads, candidate edits, atomic saves and cleanup.
- `lens/policy.py`: one audience rule for feed and direct media access.
- `lens/processing.py`: image transforms, audio trim/volume and fixed-weight mixing.
- `lens/db.py`, `schema.sql`, `storage.py`: SQLite and local/S3 files.
- `static/`: interface, editor and single-clock slideshow player.
- `tests/`: unit, integration and local browser system checks.

Google verifies university identity; verified campus accounts are approved on first sign-in. `flask --app app set-access EMAIL --approved no` disables an existing account, and every subsequent request checks that status. No separate manual approval dashboard is included.

Limits: 10 original photos (JPEG/PNG, 10 MB and 20 MP each), 3 original clips (MP3/WAV, 20 MB and 120 s each), 100 MB original uploads per post and a 60-second slideshow. Removed media are excluded from the composition; originals stay private until post deletion and continue to count towards the upload cap. Drafts and empty selected audiences are owner-only. Downloads already received cannot be revoked.

One Gunicorn process with four threads is intentional: a process-local lock serialises media mutations to bound memory. Keep one worker unless the processing coordination is redesigned. SQLite, server disk and S3 need backups for long-term use.
