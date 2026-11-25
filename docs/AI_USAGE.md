# AI assistance and validation

Tool: ChatGPT / Codex. The implementation was AI-assisted. The following records describe checks performed during this build, not an independent team review.

| Task | Output and decision | Evidence |
|---|---|---|
| Requirements | Implement the approved campus photo/audio scope with plain JavaScript, Flask, SQLite, Pillow/FFmpeg and private S3. | Compared the project brief and A4/A5 before coding. |
| Storage and saving | Prepare immutable derivatives, switch active media/audience in one transaction, queue failed deletions. Accepted with revisions. | Integration tests inject failed writes, processing and final transaction; saved content remains accessible. |
| Privacy | Use the same visibility predicate for feed and direct post/media access. | Five-user audience matrix, direct original/cross-post tests, browser recipient/excluded-user and revocation checks. |
| Processing | Crop/rotate/resize/filter and trim/gain/mix using existing libraries. | Small crop dimensions and original hash; real FFmpeg duration, silence and fixed averaging tests. |
| Concurrency | Serialise media mutations within one threaded worker. | Review identified cleanup/write races and memory pressure; count-boundary concurrent upload test and revision conflicts pass. |
| Interface | One editor and a single playback clock; responsive feed, profiles and circles. | Real local Chromium workflow and responsive widths, plus JavaScript boundary tests. |
| Deployment | Manual deployment with systemd, external configuration/database and role-based S3 access. | Shell syntax and configuration review. Full EC2 deployment remains a separate validation step. |

Representative task: “Build the campus sharing workflows in A4/A5, preserve original media, enforce each audience at the server, and test invalid input, revocation and interrupted saves.” This summarises the implementation task; it is not a verbatim transcript.

Generated code and test results require team understanding and review before submission. No actual private recordings, credentials or personal data were used as test fixtures. Local sample identities and illustrations are fictional. Hosted Google/S3 tests must be recorded after deployment; local mocks are not evidence of those services working in the full app.
