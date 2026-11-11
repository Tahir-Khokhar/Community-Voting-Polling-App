# Commit Plan — Community Voting & Polling App

This file documents the work done on the project so the GitHub commit history
shows it clearly. Apply the commits in order (each is self-contained: the app
runs and the test suite passes after every commit).

Verification before you start (should be green):

```bash
python manage.py check                 # 0 issues
python manage.py makemigrations --check --dry-run   # no changes detected
python manage.py test polls            # 88 tests: 87 pass, 1 skipped (Postgres-only)
```

---

## Recommended commit sequence

The changes touch a few files (`views.py`, `config/settings.py`,
`polls/templatetags/poll_extras.py`, `polls/templates/polls/base.html`) in more
than one theme. For a clean, theme-by-theme history use `git add -p` to stage
only the hunks listed under each commit. If you prefer one big commit, jump to
the [All-in-one fallback](#all-in-one-fallback) at the bottom.

### Commit 1 — voting engine: lock poll row + state checks inside the transaction

```bash
git add polls/models.py polls/migrations/0003_vote_vote_rank_null_or_positive.py
git commit -m "fix(voting): lock Poll row and move state checks inside cast_vote transaction

Move the expiry / auth / has_voted checks inside transaction.atomic() after
locking the Poll row with select_for_update(), so the state checks are
consistent with the writes and a poll cannot receive votes after expiry or
while a state transition is in flight. Input validation stays outside the
lock so malformed requests never contend with real voters.

Also add a CheckConstraint (rank IS NULL OR rank >= 1) on Vote as
database-level defence in depth alongside the app-level validation.

Files:
- polls/models.py                          (cast_vote refactor + CheckConstraint)
- polls/migrations/0003_vote_vote_rank_null_or_positive.py"
```

### Commit 2 — anonymous voting: align cookie lifetime with token + add throttle

Stage with `git add -p`:
- `polls/views.py`: the `_attach_token_cookie` change (max_age →
  `ANON_COOKIE_MAX_AGE`, `secure=not settings.DEBUG`) and the throttle block at
  the top of `VoteView.post`.
- `polls/throttling.py` (whole file).
- `config/settings.py`: the `ANON_COOKIE_MAX_AGE`, `VOTE_THROTTLE_*`, and
  `CACHES` hunks.

```bash
git add -p polls/views.py config/settings.py
git add polls/throttling.py
git commit -m "fix(security): cap anonymous voter cookie at token lifetime + add vote throttle

The voter cookie previously lived for 30 days while the signed token inside
expired after 7, so a visitor whose token had expired (but whose cookie had
not) was minted a fresh token and could vote again within the cookie's life.
Align the cookie max_age with ANON_TOKEN_MAX_AGE (7 days) and mark it Secure
when DEBUG is off.

Add a dependency-free, cache-backed per-IP+poll vote-attempt throttle as an
abuse brake (the real one-vote-per-token guarantee is the signed token + the
unique_ballot_per_token constraint). Production should point CACHES at a shared
backend so the counter is consistent across workers.

Files:
- polls/throttling.py                      (new)
- polls/views.py                           (cookie fix + throttle wiring)
- config/settings.py                       (ANON_COOKIE_MAX_AGE, throttle, CACHES)"
```

### Commit 3 — performance: remove N+1 from the live results partial + listing

Stage with `git add -p`:
- `polls/templatetags/poll_extras.py`: the `percentage_bar` change (now takes
  `total`, reads the score off the choice fields instead of `choice.effective_score`).
- `polls/views.py`: the `HomeView` annotate + `Count` import.
- `config/settings.py`: none for this commit.

Whole files:
- `polls/templates/polls/partials/_results.html`
- `polls/templates/polls/home.html`
- `polls/templates/polls/poll_detail.html`
- `polls/templates/polls/poll_widget.html`
- `polls/templates/polls/poll_results_page.html`

```bash
git add -p polls/templatetags/poll_extras.py polls/views.py
git add polls/templates/polls/partials/_results.html polls/templates/polls/home.html \
        polls/templates/polls/poll_detail.html polls/templates/polls/poll_widget.html \
        polls/templates/polls/poll_results_page.html
git commit -m "perf: eliminate N+1 in live results partial and poll listing

The results partial re-ran an aggregate (poll.total_votes) and dereferenced
choice.poll per bar (~4 + 2*N queries every 3s per viewer). percentage_bar now
takes the pre-computed total and reads the score off the choice fields, and
_results.html computes total/ballots once via {% with %}.

HomeView now annotates ballot_count/choice_count (Count distinct) so the
listing fires zero per-poll COUNT queries; the detail/widget/results headers
wrap their total_ballots call in {% with %} to avoid the doubled query.

Files:
- polls/templatetags/poll_extras.py         (percentage_bar takes total)
- polls/views.py                            (HomeView annotate)
- polls/templates/polls/partials/_results.html
- polls/templates/polls/home.html
- polls/templates/polls/poll_detail.html
- polls/templates/polls/poll_widget.html
- polls/templates/polls/poll_results_page.html"
```

### Commit 4 — security: CSP per-request nonce for inline scripts + SRI on HTMX + POST sign-out

Stage with `git add -p`:
- `polls/templates/polls/base.html`: the `<script nonce=...>` on the Tailwind
  config, the `integrity`/`crossorigin` on the HTMX script, and the
  sign-out-as-POST-form change (NOT the messages block — that belongs to
  commit 7; NOT the palette/nav hunks — those belong to commit 6).
- `config/settings.py`: the `csp_nonce` context-processor hunk.

Whole files:
- `polls/middleware.py`
- `polls/context_processors.py`
- `polls/templates/polls/poll_create.html`
- `polls/templates/polls/poll_share.html`

```bash
git add -p polls/templates/polls/base.html config/settings.py
git add polls/middleware.py polls/context_processors.py \
        polls/templates/polls/poll_create.html polls/templates/polls/poll_share.html
git commit -m "feat(security): CSP nonce for all inline scripts, SRI on HTMX, POST sign-out

Generate a per-request nonce in ContentSecurityPolicyMiddleware, inject it
into script-src, and drop 'unsafe-inline' from script-src when DEBUG is off.
The inline Tailwind config script carries nonce so it runs without a blanket
'unsafe-inline'. Add an SRI integrity attribute pinning the exact HTMX 1.9.12
build so a compromised CDN cannot swap in different JS. Expose the nonce to
templates via a new csp_nonce context processor.

Also fix two latent production breakages: the inline scripts on the create
and share pages had no nonce, so under the production CSP (unsafe-inline
dropped) the '+ Add choice' button and the copy-to-clipboard buttons were
silently blocked. And the header signed users out via a GET link, which
LogoutView has rejected with 405 since Django 5.0 — sign-out is now a POST
form.

Files:
- polls/middleware.py                      (nonce generation + injection)
- polls/context_processors.py              (csp_nonce)
- config/settings.py                       (register context processor)
- polls/templates/polls/base.html          (nonce, HTMX SRI, POST sign-out form)
- polls/templates/polls/poll_create.html   (nonce on inline script)
- polls/templates/polls/poll_share.html    (nonce on inline script)"
```

### Commit 5 — feat(auth): user registration + complete password flows

Stage with `git add -p`:
- `polls/views.py`: the `SignUpView` class + the `login` / `SignUpForm` imports.

Whole files:
- `polls/forms.py`
- `config/urls.py`
- `polls/templates/polls/partials/_vote_form.html`
- `templates/registration/signup.html`
- `templates/registration/login.html`
- `templates/registration/password_change_form.html`
- `templates/registration/password_change_done.html`
- `templates/registration/password_reset_form.html`
- `templates/registration/password_reset_done.html`
- `templates/registration/password_reset_confirm.html`
- `templates/registration/password_reset_complete.html`
- `templates/registration/password_reset_email.html`

```bash
git add -p polls/views.py
git add polls/forms.py config/urls.py polls/templates/polls/partials/_vote_form.html \
        templates/registration/
git commit -m "feat(auth): user registration and complete password flows

Add the missing registration page: SignUpForm (username + email + Django's
default password validators) and a SignUpView that signs the new account in
immediately and greets it on the home page. The header gains a Sign up
button and the login page links to it; the needs-login vote box offers
'Create account' next to 'Sign in'.

Also add the templates for every built-in auth view that previously 500'd:
password change (form + done) and password reset (form, done, confirm with
invalid-link handling, complete, and the email body). The login page gains a
'Forgot your password?' link and renders per-field errors.

Files:
- polls/forms.py                            (SignUpForm)
- polls/views.py                            (SignUpView)
- config/urls.py                            (/accounts/signup/ before the auth include)
- templates/registration/signup.html        (new)
- templates/registration/login.html         (signup + forgot-password links, field errors)
- templates/registration/password_*.html    (new, 7 files)
- polls/templates/polls/partials/_vote_form.html  (create-account button)"
```

### Commit 6 — style: eye-friendly indigo palette

Stage with `git add -p`:
- `polls/templates/polls/base.html`: the `tailwind.config` brand block
  (blue -> indigo), the `html`/`body` background classes, the focus-ring and
  `accent-color` CSS, and the header nav (Sign up button, username links to
  password change).
- `polls/templates/polls/home.html`: the gradient headline hunk.

```bash
git add -p polls/templates/polls/base.html polls/templates/polls/home.html
git commit -m "style: softer indigo brand palette on a tinted page background

Swap the generic blue brand scale for indigo (warmer next to the slate
neutrals, AA-contrast on white), give the page a soft slate tint so the
white cards pop, align the focus ring and control accent colors with the
new brand, and add a subtle gradient to the home headline.

Files:
- polls/templates/polls/base.html           (brand scale, bg, focus, header nav)
- polls/templates/polls/home.html           (gradient headline)"
```

### Commit 7 — refactor: message_alert tag (remove duplicated if/elif chain)

Stage with `git add -p`:
- `polls/templatetags/poll_extras.py`: the `message_alert` inclusion tag +
  `_ALERT_CSS` / `_ALERT_ICON` blocks.
- `polls/templates/polls/base.html`: the `{% load %}` change and the messages
  block (the `{% message_alert message %}` loop).

Whole file:
- `polls/templates/polls/partials/_message_alert.html`

```bash
git add -p polls/templatetags/poll_extras.py polls/templates/polls/base.html
git add polls/templates/polls/partials/_message_alert.html
git commit -m "refactor(templates): extract message_alert tag, drop duplicated if/elif

base.html duplicated the same four-way 'error/success/warning/else' branch
twice (once for the alert CSS, once for the SVG icon). Extract a
message_alert inclusion tag that decides severity (highest wins, fallback
info) in one place and renders the alert via _message_alert.html.

Files:
- polls/templatetags/poll_extras.py         (message_alert tag)
- polls/templates/polls/partials/_message_alert.html   (new)
- polls/templates/polls/base.html           (messages block simplified)"
```

### Commit 8 — config/deploy: env-driven DB/email/cache + .env.example

Stage with `git add -p`:
- `config/settings.py`: the `DATABASES` env block and the `EMAIL_*` block.

Whole file:
- `.env.example`

```bash
git add -p config/settings.py
git add .env.example
git commit -m "feat(config): env-driven database, email, and cache + .env.example

Make DATABASES env-driven so production can point at PostgreSQL
(DJANGO_DB_ENGINE) without a code edit, while dev keeps zero-config SQLite.
Add env-driven email config for the auth password-reset flow. Document every
environment variable in .env.example. manage.py check --deploy reports 0
issues with a strong DJANGO_SECRET_KEY and DEBUG=False.

Files:
- config/settings.py                       (env-driven DATABASES + EMAIL)
- .env.example                             (new)"
```

### Commit 9 — tests: full-flow coverage on top of unit tests (security, perf, concurrency, auth)

```bash
git add polls/tests.py
git commit -m "test: expand suite to 88 tests across security, perf, and full flows

Add coverage for: anonymous cookie flags (HttpOnly/SameSite/max-age <= token
max-age/Secure-in-prod), CSP header + nonce + unsafe-inline dropped in prod
plus a regression that every inline script carries the nonce, frame
restrictions (normal deny / widget allow), freeze authorization (IDOR:
anonymous/non-owner/owner/superuser), an N+1 query-count invariant, the
vote-attempt throttle, a threaded ConcurrentVoteTests (TransactionTestCase,
PostgreSQL-gated because SQLite raises SQLITE_LOCKED on concurrent writes),
the message_alert tag across all severities plus the freeze flow, full
end-to-end flows (create formset valid/rejected variants, ranked voting over
HTTP, share + widget pages, login/logout with POST-only sign-out, idempotent
seed command, admin pages), and the auth stack: signup (render, create +
auto sign-in, duplicate username, password mismatch, weak password,
authenticated redirect) and the password reset/change journeys end to end.

88 tests: 87 pass + 1 skipped (Postgres-only concurrency test).
Files:
- polls/tests.py"
```

### Commit 10 — docs: rewrite README

```bash
git add README.md
git commit -m "docs: rewrite README with architecture, security, and the key distinctions

Full README covering: overview, features, technologies, architecture,
database schema, installation, environment variables, migrations, development,
testing (SQLite + the PostgreSQL path), production deployment, security
considerations, the five required distinctions (anonymous vs authenticated,
one-vote-per-token vs one-vote-per-human, hiding results vs closing voting,
SQLite vs PostgreSQL testing, local vs production), URL routes, and known
limitations.

Files:
- README.md"
```

---

## All-in-one fallback

If you would rather push the whole change set as a single commit:

```bash
git add -A
git commit -m "Transform polling app: harden voting engine, add registration + password
flows, fix anon-cookie/token lifetime mismatch, add CSP nonce + HTMX SRI +
POST sign-out, remove N+1 from live results, add vote-attempt throttle,
env-driven DB/email/cache, indigo palette, refactor message alerts, expand
tests to 88, rewrite docs.

Highlights
- Voting: lock Poll row + move expiry/has_voted checks inside the atomic
  block; add Vote.rank CheckConstraint (migration 0003).
- Auth: registration page (SignUpForm + SignUpView, auto sign-in) and
  templates for every built-in password change/reset view (previously 500s).
- Security: align anon voter cookie max_age with signed-token max_age;
  Secure cookie in prod; CSP per-request nonce on every inline script
  (drops unsafe-inline in prod); SRI on HTMX 1.9.12; cache-backed
  per-IP+poll vote throttle; sign out via POST (LogoutView rejects GET).
- Fix: login page renders per-field errors, not only non-field errors.
- Style: indigo brand palette on a soft slate page tint; gradient headline.
- Performance: percentage_bar takes the pre-computed total (no per-choice
  aggregate or choice.poll lookup); HomeView annotates ballot/choice counts;
  header total_ballots calls wrapped in {% with %}.
- Refactor: message_alert inclusion tag removes the duplicated if/elif chain.
- Config: env-driven DATABASES / EMAIL / CACHES; .env.example documents all vars.
- Tests: 88 (87 pass + 1 Postgres-only skipped). check --deploy: 0 issues.
- Docs: README rewritten with schema, security, distinctions, limitations.

Verified: python manage.py check (0 issues), check --deploy (0 issues),
makemigrations --check (no drift), manage.py test polls (87 pass, 1 skipped)."
```

---

## After committing — push to GitHub

```bash
# from your polling_app repo root (init one if you haven't):
#   git init && git branch -m main
git remote add origin git@github.com:<you>/<repo>.git
git push -u origin main
```

## Verify the pushed state

```bash
python manage.py check
python manage.py check --deploy   # with a strong DJANGO_SECRET_KEY + DEBUG=False
python manage.py test polls
```
