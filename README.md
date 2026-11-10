# Community Voting & Polling App

A Django + HTMX polling application with live vote counts, single-choice and
ranked (Borda) voting, anonymous and authenticated modes, poll expiry,
owner-controlled result freezing, an iframe-embeddable widget, QR-code sharing,
a strict Content Security Policy, and race-safe vote counting.

Built with **class-based views throughout**, **Modern Minimal** styling
(Tailwind + Inter), signed anonymous voter tokens, and a single write path
(`Poll.cast_vote()`) guarded by database transactions and unique constraints.

---

## Contents

1. [Project overview](#project-overview)
2. [Main features](#main-features)
3. [Technologies used](#technologies-used)
4. [Architecture overview](#architecture-overview)
5. [Database schema](#database-schema)
6. [Installation](#installation)
7. [Environment variables](#environment-variables)
8. [Database migration instructions](#database-migration-instructions)
9. [Development instructions](#development-instructions)
10. [Testing](#testing)
11. [Production deployment](#production-deployment)
12. [Security considerations](#security-considerations)
13. [Key concepts & distinctions](#key-concepts--distinctions)
14. [URL routes](#url-routes)
15. [Known limitations](#known-limitations)

---

## Project overview

The application is a community polling tool: a visitor opens the home page,
creates a poll with a handful of choices, and shares a short slug-based URL.
Voters pick an option (single polls) or rank every option (ranked polls); the
results render as animated percentage bars that refresh themselves every few
seconds without a full page reload. Voting is one-vote-per-identity, enforced
at the database level — by a unique constraint per authenticated user, or by a
signed anonymous token per browser for unauthenticated polls.

---

## Main features

- Create polls with an inline choice formset (single-choice or ranked).
- Single-choice voting and ranked-choice voting scored by **Borda count**.
- Anonymous voting (signed, tamper-proof per-browser token) **and** authenticated voting.
- Account registration (auto sign-in on success), login, password change, and email-based password reset.
- Live vote-count updates via HTMX (configurable poll interval).
- Poll expiry (voting closes at a set time) and owner-controlled result freezing (results hidden while voting stays open).
- Unique slug-based poll URLs (`django-autoslug`).
- QR-code sharing of the poll URL.
- An iframe-embeddable widget with a deliberately scoped embedding policy.
- A strict Content Security Policy with per-request nonces for inline scripts and SRI on the HTMX CDN.
- Race-safe vote counting: `transaction.atomic()` + `select_for_update()` on the Poll and Choice rows, plus database-level unique constraints.
- A lightweight, dependency-free vote-attempt throttle (abuse brake).
- A management command that seeds demo data idempotently.
- An automated test suite (unit tests on SQLite + a PostgreSQL-gated concurrency test).

---

## Technologies used

| Layer | Technology | Role |
| --- | --- | --- |
| Language | Python 3.12 | All server-side logic |
| Web framework | Django 6.1.3 | ORM, class-based views, templates, auth, admin, signing, middleware |
| Frontend interactivity | HTMX 1.9.12 (CDN, with SRI) | Live result polling and form submission via partial swaps |
| Styling | Tailwind CSS (Play CDN in dev) | Utility-first styling with a custom brand/ink palette |
| Typeface | Inter (Google Fonts) | Body and heading font |
| Database | SQLite (dev) / PostgreSQL (prod) | SQLite is zero-config; PostgreSQL is the verified production backend |
| Slug generation | django-autoslug 1.9.9 | `AutoSlugField` for unique readable poll URLs |
| QR codes | qrcode 8.2 + Pillow 11.3.0 | Generate the share-URL QR PNG |

Only four packages beyond the standard library are required (see
`requirements.txt`); all are pinned to exact versions.

---

## Architecture overview

The project is a single Django project package (`config/`) with one application
(`polls/`). Rendering uses Django Templates + HTMX — there is no SPA framework
and no client-side build step in development. Every page is a class-based view,
and all vote writes funnel through a single service-level method,
`Poll.cast_vote()`, so the transactional counter update lives in exactly one
place rather than being duplicated across views.

**Request flow.** A `GET /<slug>/` renders either the vote form partial or the
results partial inside a `#poll-interactive` container. Submitting the vote form
does an `hx-post` to `/<slug>/vote/`, which calls `Poll.cast_vote()` and returns
the results partial. The results partial carries `hx-trigger="every 3s"` pointed
at `/<slug>/results/`, so HTMX re-fetches the bars without a full page reload.

**Security middleware.** A custom `ContentSecurityPolicyMiddleware` runs last
in the stack, builds the CSP header from the `CSP_*` tuples in `settings.py`,
generates a per-request nonce for inline scripts, and sets the related security
headers. Views can override individual directives per-response via
`response.csp_overrides` — the widget view uses this to allow framing.

---

## Database schema

Four models back the application. Denormalised counters
(`Choice.vote_count`, `Choice.borda_score`) are updated inside the same
transaction that inserts the ballot, so they are never out of sync with the
ballot rows.

### Poll
A single poll question. Fields: `title`, `description`, `slug` (unique
`AutoSlugField`), `poll_type` (single/ranked), `voting_mode`
(anonymous/authenticated), `created_by` (FK → User, `on_delete=SET_NULL`),
`created_at`, `expires_at` (nullable), `results_frozen` (bool). Indexed on
`expires_at`. Methods: `is_expired`, `is_ranked`, `requires_auth`,
`results_visible(user)`, `has_voted(user, token)`, `cast_vote(...)`.

### Choice
One option on a poll. FK → Poll (`on_delete=CASCADE`). Fields: `text`, `order`,
`vote_count`, `borda_score`. Ordered by `(order, id)`. Unique constraint
`unique_choice_text_per_poll` prevents duplicate choice text within a poll.

### Ballot
One voter's submission on a poll. FK → Poll and (optionally) → User, both
`on_delete=CASCADE`. `voter_token` stores the 16-char anonymous voter id (not
the full signed blob — see [Key concepts](#key-concepts--distinctions)). Two
**partial** unique constraints enforce one ballot per identity:

- `unique_ballot_per_user` — `unique(poll, user) where user is not null`
- `unique_ballot_per_token` — `unique(poll, voter_token) where voter_token != ""`

### Vote
One ranked row inside a ballot (one per choice for ranked polls; one row for
single polls). FK → Ballot and → Choice (`on_delete=CASCADE`), `rank` (nullable
for single polls). Unique constraint `unique_vote_per_ballot_choice` prevents a
duplicate choice within a ballot, and a `CheckConstraint` (`rank is null or
rank >= 1`) guards the rank range at the database level.

---

## Installation

**Easiest way — one command** (installs deps, runs migrations, seeds demo data,
starts the server):

```bash
cd polling_app
./run.sh          # Linux / macOS
```
```bat
run.bat           # Windows
```

Then open <http://127.0.0.1:8000/>.

**Manual way:**

```bash
cd polling_app
pip install -r requirements.txt
python manage.py migrate          # creates db.sqlite3 + all tables
python manage.py seed_polls       # creates a demo user + 5 sample polls
python manage.py runserver
```

> If you ever delete `db.sqlite3`, run `migrate` again before `runserver`.

**Demo account** (created by `seed_polls`): `demo` / `demo1234` (staff +
superuser; also reaches `/admin/`). Anonymous polls can be voted on without an
account.

---

## Environment variables

All configuration is environment-driven; defaults are dev-safe. Copy
`.env.example` to `.env` (gitignored) and fill in real values. Summary:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure dev fallback | **Required in prod.** ≥50 chars, high-entropy. |
| `DJANGO_DEBUG` | `True` | `False` in prod (enables HSTS, HTTPS redirect, Secure cookies). |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,0.0.0.0` | Comma-separated; avoid `*`. |
| `DJANGO_DB_ENGINE` | unset → SQLite | Set to `django.db.backends.postgresql` for prod. |
| `DJANGO_DB_NAME/USER/PASSWORD/HOST/PORT` | — | PostgreSQL credentials. |
| `DJANGO_CACHE_BACKEND` | `LocMemCache` | Shared backend (Redis/memcached) for the throttle in prod. |
| `DJANGO_CACHE_LOCATION` | `polls-throttle-v1` | Cache address. |
| `DJANGO_EMAIL_BACKEND` | console | `...smtp.EmailBackend` for prod password-reset. |
| `DJANGO_EMAIL_HOST/PORT/USER/PASSWORD/USE_TLS` | — | SMTP config. |
| `DJANGO_DEFAULT_FROM_EMAIL` | `noreply@localhost` | From address. |

---

## Database migration instructions

```bash
python manage.py migrate          # apply all migrations
python manage.py makemigrations   # only if you changed models
python manage.py showmigrations   # inspect state
```

Migrations are versioned and reversible. The `CheckConstraint` on `Vote.rank`
(migration `0003`) validates cleanly against existing data. Never edit the
database manually to bypass a migration.

---

## Development instructions

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_polls        # optional: demo data
python manage.py runserver         # http://127.0.0.1:8000
```

The dev settings use SQLite, the Tailwind Play CDN, and `DEBUG=True`. In
`DEBUG=True` the voter cookie is **not** marked `Secure` (so it sets over plain
HTTP) and `script-src` keeps `'unsafe-inline'` for convenience — a per-request
nonce still governs inline scripts (per the CSP spec a nonce takes precedence
over `'unsafe-inline'`).

---

## Testing

The suite lives in `polls/tests.py`.

```bash
python manage.py test polls        # run everything against SQLite
python manage.py test polls -v 2   # verbose, per-test output
```

Coverage: poll status, single-choice and ranked voting (incl. Borda scoring),
authenticated polls, race safety, token signing, the template tags, the full
HTTP view flow, anonymous cookie flags, CSP headers + nonce, frame
restrictions, freeze authorization (IDOR), the N+1 query-count invariant, and
the throttle.

### PostgreSQL

Real concurrent-writer behaviour can only be exercised on PostgreSQL — SQLite
raises `SQLITE_LOCKED` on concurrent writes to the same table (and the busy
timeout does not retry table-level locks), so the threaded concurrency test
(`ConcurrentVoteTests`) is **skipped on SQLite and runs only under PostgreSQL**.
The race *logic* itself is covered on every backend by `RaceSafetyTests`.

To run the suite (including the concurrency test) against PostgreSQL:

```bash
pip install psycopg[binary]
export DJANGO_DB_ENGINE=django.db.backends.postgresql
export DJANGO_DB_NAME=polls_test  DJANGO_DB_USER=...  DJANGO_DB_PASSWORD=...
python manage.py test polls
```

`select_for_update()` is a no-op on SQLite (its database-level write lock
already serialises writers) and takes real row locks on PostgreSQL. **Do not
treat SQLite test passes as proof of PostgreSQL row-lock behaviour** — run the
Postgres path above. MySQL is **not** a verified production backend.

---

## Production deployment

1. **Environment.** Set `DJANGO_DEBUG=False`, a strong `DJANGO_SECRET_KEY`, and
   `DJANGO_ALLOWED_HOSTS` to the real hostnames. The `if not DEBUG` block in
   `settings.py` then enables HSTS (30 days), HTTPS redirect, Secure session /
   CSRF / voter cookies, content-type nosniff, and the strict referrer policy
   automatically — no code change required.
2. **Database.** Point `DJANGO_DB_*` at PostgreSQL.
3. **Cache.** Set `DJANGO_CACHE_BACKEND` to a shared backend (Redis/memcached)
   so the vote-attempt throttle is consistent across workers.
4. **Static files.** `python manage.py collectstatic` and serve `STATIC_ROOT`
   from your web server / CDN.
5. **WSGI/ASGI server.** Run under `gunicorn` (or `uvicorn`/`daphne` if you add
   ASGI): `gunicorn config.wsgi:application`.
6. **Tailwind.** Replace the Play CDN with a locally built `tailwind.css`
   (the CDN injects inline `<style>` at runtime, which is why `style-src` keeps
   `'unsafe-inline'` in dev). With a built stylesheet you can drop
   `'unsafe-inline'` from `CSP_STYLE_SRC` entirely.
7. **Verify.** `python manage.py check --deploy` reports **0 issues** when run
   with a strong key and `DEBUG=False`.

---

## Security considerations

- **One write path.** All votes go through `Poll.cast_vote()`, which opens
  `transaction.atomic()`, locks the Poll row with `select_for_update()` (so
  state checks — expiry, auth, already-voted — are consistent with the writes),
  locks the affected Choice rows, then inserts the ballot and updates counters.
  The `IntegrityError` from a concurrent duplicate is translated into the
  `AlreadyVoted` domain error, never a 500.
- **Database-enforced uniqueness.** Partial unique constraints guarantee one
  ballot per `(poll, user)` and per `(poll, voter_token)` regardless of the
  application code path.
- **Signed anonymous tokens.** Tokens are `{poll_id}:{random_16_hex}` signed
  with `django.core.signing.TimestampSigner` (`SECRET_KEY`-keyed, with a
  `max_age`). The cookie is HttpOnly, SameSite=Lax, and Secure in production.
  Its lifetime is capped at the token's `max_age` so the cookie can never
  outlive the signed token inside it.
- **Cookie flags.** Voter cookie: HttpOnly, SameSite=Lax, Secure when
  `DEBUG=False`. Session and CSRF cookies are Secure when `DEBUG=False`.
- **CSP.** A strict baseline (`default-src 'self'`, `frame-ancestors 'none'`,
  `base-uri 'none'`, `form-action 'self'`). Inline scripts run by per-request
  nonce; `'unsafe-inline'` is dropped from `script-src` in production. The HTMX
  CDN script carries an SRI `integrity` attribute pinning the exact 1.9.12
  build. The widget view is the sole page that relaxes `frame-ancestors`.
- **Framing.** Every normal page sends `X-Frame-Options: DENY` and
  `frame-ancestors 'none'`. The widget is `xframe_options_exempt` and emits
  `frame-ancestors *` so it can be embedded; this is a deliberate, documented
  policy, not a wildcard applied globally.
- **Authorization.** `FreezeToggleView` requires login and checks
  `request.user == poll.created_by or request.user.is_superuser` server-side;
  poll creation requires login. User IDs and ownership are never trusted from
  the browser. Sign-up runs Django's password validators (minimum length,
  common-password, all-numeric) server-side before any account is created.
- **Throttle.** A per-IP+poll vote-attempt limiter (Django cache) brakes
  scripted abuse of the vote endpoint. It is an abuse brake, not a security
  boundary.
- **Output escaping.** All user content is rendered through Django's
  auto-escaping template engine; no user-supplied HTML is trusted.

---

## Key concepts & distinctions

**Anonymous vs. authenticated voting.** Anonymous polls accept a signed token
in a per-poll cookie; no account is needed. Authenticated polls require
sign-in and enforce uniqueness per user. The mode is chosen per poll at
creation.

**One vote per token vs. one vote per human.** Anonymous voting enforces one
vote per *valid voter token / browser identity*, **not** one vote per human.
A determined user can clear cookies (or wait for the token to expire, after
which a fresh token is minted) and vote again. The token prevents casual
double-voting and forgery, not determined multi-voting. Use authenticated
polls if one-vote-per-identity must be tied to an account.

**Hiding results vs. closing voting.** `results_frozen` hides the live result
counts from non-owners (voters see the form, owners/superusers see the
results) but does **not** stop voting. `expires_at` closes voting: after the
expiry, `cast_vote()` raises `PollClosed` and no ballot is accepted. The two
are independent — a poll can be frozen-while-open, or closed-while-unfrozen.

**SQLite testing vs. PostgreSQL concurrency testing.** The default test
database is SQLite, which serialises writers via a database-level lock and
raises `SQLITE_LOCKED` on concurrent table writes. This is fine for unit
testing the logic, but it does **not** exercise PostgreSQL's row-level
`select_for_update()` locks. The threaded concurrency test is therefore gated
on PostgreSQL. See [Testing → PostgreSQL](#postgresql).

**Local development vs. production configuration.** Local dev uses SQLite, the
Tailwind CDN, `DEBUG=True`, a console email backend, and a per-process
locmem cache. Production uses PostgreSQL, a shared cache (Redis/memcached), an
SMTP email backend, `DEBUG=False` (with HSTS / Secure cookies / HTTPS
redirect), and a locally built Tailwind stylesheet. All of this is selected by
environment variables — the same code runs in both.

---

## URL routes

| URL | View | Notes |
| --- | --- | --- |
| `/` | `HomeView` | Paginated list of polls (annotated counts, no N+1) |
| `/create/` | `PollCreateView` | Login required |
| `/<slug>/` | `PollDetailView` | Vote form OR live results |
| `/<slug>/vote/` | `VoteView` | POST; returns results partial (HTMX); throttled |
| `/<slug>/results/` | `ResultsPartialView` | Polled every 3s by HTMX |
| `/<slug>/results-page/` | `PollResultsView` | Full-page results |
| `/<slug>/widget/` | `WidgetView` | iframe-embeddable; `frame-ancestors *` |
| `/<slug>/share/` | `ShareView` | Share URL + QR + embed snippet |
| `/<slug>/qr.png` | `QRCodeView` | QR code PNG of the share URL |
| `/<slug>/freeze/` | `FreezeToggleView` | Owner/superuser toggles result freeze |
| `/accounts/signup/` | `SignUpView` | Registration; signs the new account in automatically |
| `/accounts/login/`, `/accounts/logout/`, `/accounts/password*` | Django built-in auth | Templates provided for every auth view |
| `/admin/` | Django admin | Poll, Choice (inline), Ballot, Vote registered |

---

## Known limitations

- **Anonymous voting is one-per-token-browser, not one-per-human.** A user who
  clears cookies or waits for token expiry (7 days) can obtain a fresh token
  and vote again. Tie voting to accounts for one-vote-per-identity.
- **Cross-origin embedded anonymous voting is limited by third-party cookie
  restrictions.** The widget sets a SameSite=Lax voter cookie, which works for
  same-origin embedding (the share-page preview). Cross-origin iframes cannot
  rely on third-party cookies (blocked by modern browsers), so anonymous voting
  inside a cross-origin widget is not guaranteed to work; the widget still
  renders and votes work for authenticated users via their session. For
  cross-origin anonymous embedding, host the widget on the same origin or have
  the embedder proxy the vote.
- **MySQL is not a verified production backend.** Migrations, partial unique
  constraints, and `select_for_update()` behaviour have been designed for
  PostgreSQL; MySQL has not been tested.
- **Dev throttle is per-process.** With the default `LocMemCache` the
  vote-attempt throttle is per worker process. Production must configure a
  shared cache backend for a consistent counter.
- **Tailwind Play CDN in development** requires `'unsafe-inline'` in
  `style-src` (it injects a generated `<style>` at runtime). Build Tailwind
  locally for production to remove it.

---

## Seeded demo polls

`python manage.py seed_polls` creates (idempotently — re-running skips polls
that already exist by title):

1. **Which feature should we build next?** — anonymous, single, expires in 7 days.
2. **Rank our next team social event** — anonymous, ranked, never expires.
3. **Best code editor for the team?** — authenticated, single.
4. **Lunch pick for Friday (closed example)** — anonymous, single, already expired.
5. **Conference talk topics — results hidden** — anonymous, single, owner-frozen.

Each poll comes with pre-cast votes so the result bars aren't empty on first
load.

---

## Project layout

```
polling_app/
├── manage.py
├── requirements.txt          # 4 pinned packages
├── .env.example              # all environment variables documented
├── README.md
├── db.sqlite3                # created by migrate
├── config/                   # Django project package
│   ├── settings.py           # CSP_* + POLL_SETTINGS + env-driven DB/email/cache
│   ├── urls.py
│   └── ...
├── polls/                    # the app
│   ├── models.py             # Poll, Choice, Ballot, Vote + cast_vote()
│   ├── views.py              # all class-based views
│   ├── forms.py              # PollCreateForm, ChoiceFormSet, vote forms, SignUpForm
│   ├── signing.py            # anonymous token mint/verify
│   ├── middleware.py         # CSP middleware (nonce + headers)
│   ├── throttling.py         # vote-attempt rate limiter
│   ├── exceptions.py         # PollClosed / AlreadyVoted / InvalidVote
│   ├── context_processors.py # poll_settings + csp_nonce
│   ├── templatetags/poll_extras.py   # {% percentage_bar %}, {% pct %}, {% has_voted %}
│   ├── management/commands/seed_polls.py
│   ├── migrations/           # 0001 initial, 0002 index, 0003 rank CheckConstraint
│   └── templates/polls/      # base, home, detail, create, share, widget, partials/
└── templates/registration/   # signup, login, logged_out, password change + reset
```
