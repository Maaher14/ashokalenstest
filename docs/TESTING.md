# Verification

## Automated checks

Executed during this build: **42 Python tests and 2 JavaScript tests passed**. The local Chromium system workflow also passed.

Python tests use the real Flask routes, temporary SQLite databases, actual local object files, Pillow and FFmpeg. Google signature verification is mocked at the library boundary; token-claim, CSRF and access checks still execute. These tests do not claim to contact Google or S3.

Coverage includes:

- Campus identity checks: hosted domain, verified email, exact email domain, issuer, nonce and rejection from Google's verification library.
- Four-audience matrix across five users; feed/direct-route parity, private drafts and original files, cross-post media IDs, disabled users and access revocation.
- 10-photo and 3-audio limits, per-file rejection, total original-byte boundary including outstanding reservations, and simultaneous admissions at the count limit.
- Hand-sized crop dimensions, original hash preservation, rotation/resize/greyscale, audio trim duration and silence, fixed averaging after a short track ends.
- Positive timing and 60-second limit; failed storage/processing/final transaction and stale revision preserve saved content. Cleanup failure queues work; restart recovery releases reservations.
- Follow/like uniqueness, self-follow rejection, group owner controls, recipient validation, profile edits and empty selected audience.
- Filtering before stable pagination, authorised byte-range delivery, no-store responses and range denial after revocation.

`node --test tests/timeline.test.mjs` imports the actual browser timeline function. It checks [3,5] boundaries at 2.999, 3, 7.999 and 8 seconds, backwards seeks, and the single-image case.

## Local browser system test

`python tests/browser_system.py` starts an isolated Flask server with a temporary database, local storage, real media processing and three fictional accounts. It uploads two images/two tracks, edits photo and audio, sets 3/5-second timing, saves, previews, plays/seeks and publishes. It tests recipient/excluded-user file access, revocation of saved media/mix URLs, circle creation/member changes, profile editing, likes and responsive widths 1440, 768, 390 and 360. It fails on browser script errors or horizontal overflow. Chromium is required. `CHROMIUM_EXECUTABLE` can select an installed Chromium binary.

This local system test was executed successfully during development. It uses the explicit local-only demo login, not a test bypass in production. Illustrated sample media are synthetic, not actual campus photographs.

## Performance observation

An isolated Flask test-client workload of 500 published records, 5 concurrent signed-in clients and 30 feed requests each measured approximately **44.9 ms median / 55.3 ms p95**, metadata only. This is a local observation with synthetic data, not a hosted performance guarantee. Re-measure with EC2, browser/network and real media. Peak image memory and worst-case processing time still need hosted measurement.

## Hosted system checks

The setup sign-in test, EC2-to-S3 upload/read/delete test and CloudFront HTTPS reachability were reported successful before this full build. The complete app must still be installed and tested on those resources. After deployment:

1. Campus Google login succeeds; personal Gmail is denied; sign-out blocks API and media access.
2. Create/edit/publish a two-photo/two-track post. Confirm timing, caption, location and playback in current Chrome and Firefox.
3. With real accounts, test campus/follower/circle/selected sharing, then revoke grants/follows/membership and retry saved post, media, range and mix URLs.
4. Confirm ordinary S3 object URLs are private. Verify originals remain owner-only.
5. Restart the service and verify database/media persist. Inspect errors and cleanup on failed processing/deletion.
6. Check keyboard operation, narrow screens, slow transfers and failed-load Retry.

Report only outcomes actually observed on the deployment. Previously downloaded files cannot be withdrawn; revocation applies to subsequent requests.
