# Deployment and repository changes

## Existing resources

- Region: Sydney, `ap-southeast-2`.
- EC2 name: `ashoka-lens-app`; Ubuntu 24.04, t3.micro.
- Private bucket: `ashoka-lens-media` with all public access blocked and SSE-S3.
- IAM role: `ashoka-lens-ec2-role`, with list/get/put/delete access only to that bucket.
- CloudFront: `d3qkghr7scdsnb.cloudfront.net`, distribution `E1M7IM1LZ5GMZY`.
- Google OAuth: the web Client ID in `.env.example`; no client secret required.

Do not commit private keys, tokens, database files, real uploads or the production environment file. The session secret is generated once with restricted file permissions in the external data directory.

## First deployment

1. Confirm the EC2 role and private bucket still match the names above. Check outbound access and disk space.
2. Add the CloudFront HTTPS origin to the existing Google Web client. Keep localhost:5001 for local work.
3. SSH from your Mac: `ssh -i ~/Downloads/ashoka-lens-key.pem ubuntu@3.106.216.96` (use the current EC2 IP if changed).
4. Clone and run the installer in README. It uses `/var/lib/ashoka-lens` for persistent data and `/etc/ashoka-lens.env` for configuration. It does not replace the bucket or copy the local sample database.
5. Open the CloudFront URL. Sign in with a campus account, upload two photos and two audio clips, edit, save a draft, preview and publish. Use another campus account to test sharing, revocation and direct media URLs.

`systemctl status ashoka-lens` shows service health. `sudo journalctl -u ashoka-lens -n 60 --no-pager` shows errors. `sudo systemctl restart ashoka-lens` restarts the app. `sudo nginx -t` validates Nginx. No permanent AWS access keys belong in configuration.

## Updates

From the code checkout, run `git pull --ff-only`, then `sudo bash deploy/install.sh`. Back up the database before schema changes. The schema is created idempotently; it is not a migration framework. A new incompatible schema needs an explicit migration, not deletion of the live database.

The installer is intended for this dedicated coursework EC2 instance: it replaces the default Nginx site, adds the Ashoka Lens service, and installs dependencies. Inspect it first if the host also serves other applications. It does not delete files from the earlier `~/ashoka-lens` sign-in test.

## Connection security

Browser to CloudFront uses HTTPS with secure session cookies. The currently configured CloudFront-to-EC2 hop is **HTTP**, so this is not end-to-end encryption. Keep that limitation explicit. For protection against direct origin requests, add a randomly generated `X-Lens-Origin` header in CloudFront and make Nginx reject a missing/incorrect value, or restrict the origin security group to the CloudFront origin-facing managed prefix list. Never put the header value in Git. Further origin TLS requires a certificate matching a hostname you control, or another supported origin arrangement.

`CachingDisabled` applies to every path. Forward all cookies, headers and query strings using `AllViewer`. Every post and file route checks current permissions, and returns `no-store`; no S3 URLs are exposed. The app buffers large downloads to temporary disk, then supports browser range delivery. Ensure temporary disk capacity is available.

## Switching repositories

Copy source, tests and documentation into the assigned repository while preserving its course files. On EC2, update `origin` with `git remote set-url origin NEW_URL` if histories match, or clone the official repo into a new directory and rerun `deploy/install.sh` there. Do not copy `.git`, `.venv`, `instance`, credentials or sample data.

Database, session key, production config, bucket and CloudFront remain unchanged. Any GitHub Actions settings must be recreated in the new repo. The included workflow runs tests only; it does not deploy or hold AWS credentials. Google authorised origins change only if the website hostname changes.

Stopping and starting EC2 may change its public IP/DNS. If it changes, update the CloudFront origin and SSH address. The public CloudFront URL stays the same.

## Cleanup and backups

The service recovers interrupted jobs before starting. Normal mutations retry pending cleanup. To explicitly retry, run the `cleanup` Flask command with the production environment loaded, or restart the service. Delete first removes access in SQLite, then attempts S3 deletion; failed deletions remain queued.

Use SQLite's backup API rather than copying an actively written database file. Keep backups outside the repository and protect them as private user data. Check your AWS credits and trial date in AWS Settings; no account upgrade is part of deployment.
