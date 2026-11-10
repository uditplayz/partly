# partly

Find parties near you and get on the guest list.

Partly is an installable web app for hosting and joining small local hangouts: house parties, rooftop jams, workshops, study sessions, chai breaks. Hosts keep their address private until they confirm a guest. Rooms never overfill. Guests get in by showing a QR pass at the door.

> **Status: early development.** All 6 phases are built: accounts, the installable app shell, offline support, event drafts, the filterable feed, the listing-fee checkout, RSVPs with approvals, a waitlist and invitations, QR passes with a door check-in scanner, and a Celery email pipeline with scheduled reminders and trust scores, all covered by tests. The checkout runs in a sandbox; the Razorpay adapter is written but has not been run against live Razorpay yet. The camera scanner has not yet been tried on a real phone, and offline pass display has not been checked in a browser. The Celery worker and beat have been run once against Redis 7 on Windows; tests run tasks inline. See [Roadmap](#roadmap).

## Why

Small hangouts usually get organised in group chats. Addresses get forwarded to people the host never approved, twelve people say "in" for a room of eight, and nobody knows who actually showed up. Ticketing platforms are built for concerts, not for a host with six chairs and a kettle.

Partly is built around a few rules:

- **The feed shows the neighbourhood, never the street.** The exact address only appears for confirmed guests.
- **No maps, no location pins.** A pin on a map shows where a private home is.
- **No money between guests and hosts.** Hosts list a cover charge ("₹200 at the door") and collect it at the venue. Partly only charges hosts a small flat fee to publish a listing.

## Features

| | Feature | Status |
| --- | --- | --- |
| Accounts | Sign up, log in with username or email, profiles with vibe tags | ✅ Built |
| App shell | Installable PWA, offline page, light and dark themes, mobile bottom nav | ✅ Built |
| Feed | List of events filtered by vibe, area, date, free entry and open spots | ✅ Built |
| Hosting | Draft and edit events, My Hosting dashboard | ✅ Built |
| Publishing | Publish an event after paying a listing fee: sandbox UPI checkout, signed webhooks, Razorpay adapter | ✅ Built (sandbox) |
| RSVPs | Capacity limits, optional host approval, waitlist, email invitations, My Tickets, guest manager for hosts | ✅ Built |
| Check-in | Signed QR pass for each guest; the host scans it with a phone camera, with a manual fallback and live counts | ✅ Built (camera untested on device) |
| Email | Confirmations with the QR pass, host alerts, invitations, cancellation notices, reminders 24 h and 2 h before start (HTML and plain text, sent by Celery) | ✅ Built |
| Trust | Stored score from attendance, hosting and host cancellations, recomputed after each event and nightly | ✅ Built |

## Tech stack

- **Backend:** Python, Django 5.2 LTS, PostgreSQL
- **Frontend:** Django templates, Bootstrap 5 (restyled with CSS variables), vanilla JavaScript
- **Background jobs:** Celery, Redis, django-celery-beat
- **QR:** segno (generating passes), html5-qrcode (camera scanning)
- **PWA:** web manifest, a service worker served from `/`, offline fallback page

## Getting started

### Prerequisites

- Python 3.13 or 3.14
- PostgreSQL 14 or newer (developed on 18)
- Redis, only if you run a real worker. Development runs tasks inline without it. The quickest route is Docker: `docker run -d --name partly-redis -p 6379:6379 redis:7-alpine`.

### Setup

```bash
git clone <this-repo-url> partly
cd partly

python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
cp .env.example .env          # then edit DATABASE_URL and SECRET_KEY
createdb partly               # or: psql -c "CREATE DATABASE partly"

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py seed_demo         # optional: 40 demo events (login demo_aditi / partly-demo-pass)
python manage.py runserver
```

Open http://localhost:8000.

To check the PWA, open Chrome DevTools → **Application**. You should see a valid manifest and a service worker active at scope `/`. Switch the Network tab to offline and reload to see the offline page.

### Configuration

All settings come from environment variables, loaded from `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | `dev`, `test` or `prod` |
| `SECRET_KEY` | none | Required in production |
| `DEBUG` | `False` | `True` for local development |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated |
| `SITE_URL` | `http://localhost:8000` | Base URL used for links in emails |
| `CSRF_TRUSTED_ORIGINS` | empty | Add your tunnel URL when testing on a phone |
| `DATABASE_URL` | `postgres://postgres@localhost:5432/partly` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker. Required in production (no fallback) |
| `CELERY_TASK_ALWAYS_EAGER` | `True` in dev, `False` elsewhere | Run tasks inline without Redis. Forced off in production |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | console backend in dev, SMTP in production | Where email goes |
| `PLATFORM_LISTING_FEE_INR` | `49` | Fee charged to publish an event. `0` publishes without checkout |
| `PAYMENT_PROVIDER` | `mock` | `mock` (sandbox, no real money) or `razorpay`. Production refuses `mock` unless `ALLOW_MOCK_PAYMENTS=True` |
| `PAYMENT_ORDER_TTL_MINUTES` | `30` | How long an unpaid checkout stays open |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | empty | Needed for `razorpay`. Point a Razorpay webhook for `payment.captured` and `payment.failed` at `/payments/webhook/razorpay/` |
| `PWA_CACHE_VERSION` | `v1` | Change this to make browsers reload cached files |

### Background jobs

With `CELERY_TASK_ALWAYS_EAGER=False` and a reachable `REDIS_URL`, run a worker and the scheduler as two processes:

```bash
celery -A config worker -l info --pool=solo   # --pool=solo is needed on Windows
celery -A config beat -l info
```

`migrate` installs four periodic jobs (reminders and event completion every 15 minutes, payment-order expiry every 10, trust scores nightly at 03:30 IST). They live in the database, so you can pause or retime them in the Django admin.

### Deploying with Docker

`docker-compose.yml` runs the web server (gunicorn), a Celery worker, Celery beat, PostgreSQL 17 and Redis 7. A one-shot `migrate` service runs first.

```bash
cp .env.production.example .env.production   # fill it in; it is gitignored
export POSTGRES_PASSWORD=choose-a-strong-one
docker compose up -d --build
```

The image installs from `requirements.lock` (exact versions with hashes, wheels only), runs as a non-root user and serves hashed static files through WhiteNoise. `/healthz/` checks the database. TLS is not included: put a reverse proxy in front of port 8000 that sends `X-Forwarded-Proto: https`, and keep `SECURE_SSL_REDIRECT` on. Set `SECURE_SSL_REDIRECT=False` only to try the stack over plain HTTP on your own machine. Regenerate both lock files with `pip-compile` after changing `requirements*.txt`.

Checked on this project: the stack builds and comes up with Docker on Windows, `/healthz/` and the feed return 200, hashed static files are served, the security headers are present, and the worker connects to Redis. Not checked: a real server with a domain and TLS, real SMTP, Razorpay live, backups of the `pgdata` volume (set those up yourself).

### Running tests

```bash
pytest
```

GitHub Actions (`.github/workflows/ci.yml`) installs from `requirements-dev.lock` (exact versions with hashes; regenerate with `pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements-dev.lock requirements-dev.txt` after changing `requirements*.txt`) and runs the same suite on Linux against PostgreSQL, plus a migrations check and Django's deploy checks on the production settings.

Tests run against a real PostgreSQL database. The test runner creates and removes `test_partly` itself, so the database user needs permission to create databases.

### Testing on a phone

The camera scanner needs HTTPS. `localhost` counts as secure, but a phone on your network does not. Use a tunnel such as `cloudflared` or `ngrok`, and add the tunnel URL to `CSRF_TRUSTED_ORIGINS`.

## Project layout

```
config/            settings (base, dev, test, prod), URLs, Celery app
apps/
  core/            layout, PWA (manifest, service worker, offline page), shared constants
  accounts/        custom User model, auth, profiles
  events/          events, feed, filters, hosting dashboard, seed_demo command
  payments/        listing-fee checkout, providers (mock, Razorpay) and the webhook
  rsvps/           RSVPs, waitlist, invitations, My Tickets, guest manager (QR passes, door scanner, check-in)
  notifications/   Celery tasks, email builders, beat schedule
templates/         Django templates; the service worker is rendered from here
static/            CSS design tokens, JavaScript, icons, vendored Bootstrap
```

## Design decisions

The rules that keep Partly safe live in the database and in a few narrow code paths, not only in the user interface.

- **Seats are claimed one request at a time.** Every RSVP change locks the event row (`select_for_update`), so two people can't both take the last spot.
- **Only a verified payment publishes an event.** A listing goes live only when the signed payment webhook arrives. Landing on the "success" page is not enough.
- **The address never reaches the feed.** It is excluded from feed database queries, not just hidden in the template.
- **Emails go out only after data is saved.** Tasks are queued with `transaction.on_commit` and receive IDs, so a rolled-back RSVP never triggers a confirmation.
- **Reminders can't double-send.** Each reminder is claimed with an atomic update before sending. If sending fails, the claim is released and the next run retries.
- **Old passes stop working.** Each RSVP's pass token changes whenever it is cancelled, declined or re-requested.
- **An invite works only for the person invited.** It skips host approval but never capacity, and the link is tied to the invited email or account, so forwarding it doesn't let someone else in.
- **A strict Content-Security-Policy.** Pages allow scripts only from this site plus one nonce-tagged inline script (the theme setter), and no inline styles. Only the Razorpay checkout page gets a wider policy. Set `CSP_REPORT_ONLY=True` to log violations instead of blocking them, or `CSP_ENABLED=False` to turn it off. The camera is allowed for this site's own pages only (`Permissions-Policy`).
- **Reminders can't be lost or doubled.** The scheduler claims each reminder with a conditional database update before queueing it, so two scheduler processes can't both send. If sending fails for good, the claim is released and the next run retries. A bug that fails every time would therefore retry every 15 minutes until fixed.
- **Trust score is a plain formula.** `50 + 30 × attendance rate + 2 per hosted event (max 10) − 5 per event the host cancelled after publishing (max 4)`, clamped to 0 to 100. Attendance counts only confirmed guests on completed events. Accounts with fewer than 3 past events show as "New".
- **Logging out clears saved passes.** Tickets are cached for offline use at the venue. Logout clears that cache so the next person on a shared phone can't see them.

## Roadmap

Each phase is finished only when its tests pass and it has been checked by hand.

1. ✅ **Foundation and PWA shell:** accounts, design system, installable offline app
2. ✅ **Events and feed:** drafts, filters, fast area search, demo data
3. ✅ **Listing-fee checkout:** sandbox UPI, signed webhooks, Razorpay adapter (not yet tested against live Razorpay)
4. ✅ **RSVP engine:** capacity, approvals, waitlist, invitations, overbooking tests under concurrent requests
5. ✅ **QR passes and scanner:** signed passes, host camera check-in, offline tickets (camera and offline caching not yet checked on a device)
6. ✅ **Email and reminders:** Celery pipeline, scheduled reminders, trust score, production settings (worker and beat checked once against Redis on Windows)

## Contributing

The project is moving quickly and the data model is still settling. Open an issue before starting anything large. For pull requests:

- Run `pytest` before pushing and add tests for new behaviour.
- Keep business rules in service functions and database constraints, not in views or templates.
- Stay within the design tokens in `static/css/tokens.css`. No alarm-red: errors use the clay colour.

## License

No license has been chosen yet. Until one is added, all rights are reserved by the author.
