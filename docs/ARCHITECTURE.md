# How Ashoka Lens works

The browser sends JSON and sequential file uploads to Flask. CloudFront supplies the public HTTPS address, with caching disabled. Nginx forwards to one threaded Gunicorn worker. SQLite stores structured records on EC2 disk; original files, edited copies and mixed audio live in private S3. Local mode substitutes a private filesystem directory for S3.

Google returns an ID token. Google's library verifies the signature, intended client, issuer and expiry. The server also checks the login nonce, verified email, exact campus email domain and hosted domain. A verified campus identity creates an approved local account; a stored disabled status prevents future access. Each mutation needs a session CSRF token. Sessions use a persistent secret, HttpOnly/SameSite cookies and Secure cookies in production.

## A post's lifetime

1. Create an owner-only draft.
2. Validate and admit each upload against count/byte limits, with persisted reservations. Decode and store its preserved original; create a candidate publication copy. Originals are never delivered to other users.
3. Make edits from the preserved original. Candidates do not replace published files yet.
4. Save ordered candidate IDs, durations, caption, location and audience. Validate input and prepare the soundtrack first. Check the expected revision again inside a short SQLite transaction; switch all active references and grants together. Only then remove superseded derivatives and old mixes.
5. Delete by marking the post deleted before removing records/files. Failed object deletion remains in Cleanup for retry.

Interrupted jobs are marked Failed before the service starts. Upload failures with no saved original require re-upload. Failed edits can retry a saved original. A failed mix is retried by saving the composition again. No external job queue is used. A process-local lock bounds concurrent media work; the deployment intentionally uses one worker. Disk and network failures can leave queued objects, which the recovery/cleanup commands handle.

## Access policy

Owners can view their drafts and originals. Other users require a published post and a matching audience: all campus members, a current follower, a member of a selected circle, or an explicitly selected user. Media must belong to that post and be an active derivative. A single SQL predicate supplies both feed filtering and direct access checks. Groups are owner-managed; current membership applies immediately. Feed filtering happens before 20-row pagination.

## Composition

The image pipeline is orientation, crop, clockwise rotation, resize, filter and brightness/contrast. Publication copies exclude EXIF/GPS. Audio is trimmed and gain-adjusted before mixing. Each selected track starts at zero, is silence-padded/cut to the slideshow length, then mixed with fixed equal weights. There are no arbitrary offsets or loops.

The player fetches authorised media into temporary browser blobs and preloads before playback. With sound it uses the mixed audio's clock; silent posts use pause-aware elapsed time. At each frame or seek, it scans cumulative photo durations. At an exact boundary the next photo appears; at the total duration playback ends. Blob URLs are released when the player closes. Already fetched media cannot be revoked retroactively.

## Boundaries

This is a small coursework deployment, not a campus-wide scale claim. SQLite has one writer, media processing is synchronous, and downloads use server bandwidth/temporary disk. The current CloudFront-to-EC2 hop is HTTP, despite HTTPS at the browser. See deployment notes before wider use. No video, messaging, comments, map interface or recommendation engine is included.
