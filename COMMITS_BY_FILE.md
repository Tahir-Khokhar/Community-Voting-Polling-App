# File-by-File Commit Guide — Community Voting & Polling App

One ready-to-paste commit for **every file** in the project (59 files, 59 commits), in an
order that builds the project sensibly: scaffolding → app core → views → templates →
docs. This guide is deliberately kept **outside the project folder** so the zip and the
project itself stay untouched.

Use this **instead of** (or as an alternative to) the 10-commit plan in the project's
`COMMITS.md` — both produce the same final state; this one gives maximum granularity.

## One-time setup

```bash
cd polling_app
git init
git branch -m main
git config user.name  "Your Name"
git config user.email "you@example.com"
```

Notes:
- `db.sqlite3` is **never committed** — it is already excluded by `.gitignore` (commit #1).
- Every block below is a whole-file `git add`, so no interactive `git add -p` is needed here.
- Run the blocks strictly top-to-bottom the first time.

## Quick map — file → commit

| # | File | What it is |
| --- | --- | --- |
| 1 | `.gitignore` | Ignores db, caches, env files, editor junk |
| 2 | `.env.example` | All environment variables documented |
| 3 | `requirements.txt` | 4 pinned packages |
| 4 | `manage.py` | Django entry point |
| 5 | `run.sh` | Linux/macOS one-command launcher |
| 6 | `run.bat` | Windows one-command launcher |
| 7 | `config/__init__.py` | Project package |
| 8 | `config/settings.py` | Settings: CSP, env-driven DB/email/cache |
| 9 | `config/wsgi.py` | WSGI entry point |
| 10 | `config/asgi.py` | ASGI entry point |
| 11 | `polls/__init__.py` | App package |
| 12 | `polls/apps.py` | App configuration |
| 13 | `polls/exceptions.py` | PollClosed / AlreadyVoted / InvalidVote |
| 14 | `polls/signing.py` | Signed anonymous voter tokens |
| 15 | `polls/throttling.py` | Vote-attempt rate limiter |
| 16 | `polls/models.py` | Poll, Choice, Ballot, Vote + cast_vote() |
| 17 | `polls/migrations/__init__.py` | Migrations package |
| 18 | `polls/migrations/0001_initial.py` | Initial schema |
| 19 | `polls/migrations/0002_...slug...idx.py` | Slug index adjustment |
| 20 | `polls/migrations/0003_vote_vote_rank_null_or_positive.py` | rank CheckConstraint |
| 21 | `polls/admin.py` | Admin registration with inline choices |
| 22 | `polls/context_processors.py` | poll_settings + csp_nonce |
| 23 | `polls/middleware.py` | CSP middleware (nonce + headers) |
| 24 | `polls/templatetags/__init__.py` | Templatetags package |
| 25 | `polls/templatetags/poll_extras.py` | percentage_bar, pct, has_voted, message_alert |
| 26 | `polls/forms.py` | Create formset, vote forms, SignUpForm |

kal push kara ga
| 27 | `polls/urls.py` | App routes |
| 28 | `polls/views.py` | All class-based views incl. SignUpView |
| 29 | `config/urls.py` | Root URLs (signup + auth include + polls) |
| 30 | `polls/management/__init__.py` | Management package |
| 31 | `polls/management/commands/__init__.py` | Commands package |
| 32 | `polls/management/commands/seed_polls.py` | Idempotent demo-data seeder |
| 33 | `polls/tests.py` | 88-test suite |
| 34 | `polls/templates/polls/base.html` | Base layout: palette, HTMX, header, messages |
| 35 | `polls/templates/polls/home.html` | Home page |
| 36 | `polls/templates/polls/poll_create.html` | Create page |
| 37 | `polls/templates/polls/poll_detail.html` | Detail page |
| 38 | `polls/templates/polls/poll_results_page.html` | Full-page results |
| 39 | `polls/templates/polls/poll_share.html` | Share page (QR + embed) |
| 40 | `polls/templates/polls/poll_widget.html` | Iframe widget |
| 41 | `polls/templates/polls/partials/_bar.html` | Result bar partial |
| 42 | `polls/templates/polls/partials/_vote_form.html` | Vote form partial |
| 43 | `polls/templates/polls/partials/_results.html` | Live results partial |
| 44 | `polls/templates/polls/partials/_results_frozen.html` | Frozen-results partial |
| 45 | `polls/templates/polls/partials/_message_alert.html` | Message alert partial |
| 46 | `templates/registration/signup.html` | Registration page |
| 47 | `templates/registration/login.html` | Login page |
| 48 | `templates/registration/logged_out.html` | Signed-out page |
| 49 | `templates/registration/password_change_form.html` | Change password |
| 50 | `templates/registration/password_change_done.html` | Change success |
| 51 | `templates/registration/password_reset_form.html` | Request reset |
| 52 | `templates/registration/password_reset_done.html` | Reset sent |
| 53 | `templates/registration/password_reset_confirm.html` | Set new password |
| 54 | `templates/registration/password_reset_complete.html` | Reset done |
| 55 | `templates/registration/password_reset_email.html` | Reset email body |
| 56 | `static/css/.gitkeep` | Keep CSS dir |
| 57 | `static/js/.gitkeep` | Keep JS dir |
| 58 | `README.md` | Full documentation |
| 59 | `COMMITS.md` | 10-commit logical plan |

---

## Stage 1 — Project scaffolding (commits 1–6)

#### 1. `.gitignore`

```bash
git add .gitignore
git commit -m "chore: add .gitignore (dev database, caches, env files, editor junk)"
```

#### 2. `.env.example`

```bash
git add .env.example
git commit -m "chore(config): document every environment variable in .env.example"
```

#### 3. `requirements.txt`

```bash
git add requirements.txt
git commit -m "chore(deps): pin runtime deps — Django, django-autoslug, qrcode, Pillow"
```

#### 4. `manage.py`

```bash
git add manage.py
git commit -m "chore: add manage.py entry point"
```

#### 5. `run.sh`

```bash
git add run.sh
git commit -m "feat(dev): one-command launcher for Linux/macOS (deps + migrate + seed)"
```

#### 6. `run.bat`

```bash
git add run.bat
git commit -m "feat(dev): one-command launcher for Windows (deps + migrate + seed)"
```

## Stage 2 — Project package (commits 7–10)

#### 7. `config/__init__.py`

```bash
git add config/__init__.py
git commit -m "chore(config): project package"
```

#### 8. `config/settings.py`

```bash
git add config/settings.py
git commit -m "feat(config): settings with CSP config, POLL_SETTINGS, env-driven DB/email/cache" -m "Strict CSP_* configuration consumed by the middleware, POLL_SETTINGS (live-update interval, throttle limits, anon-token max-age), env-driven DATABASES (zero-config SQLite in dev, DJANGO_DB_* for PostgreSQL in production), env-driven EMAIL_* for the password-reset flow (console backend in dev), and Secure session/CSRF cookies when DEBUG is off."
```

#### 9. `config/wsgi.py`

```bash
git add config/wsgi.py
git commit -m "chore(config): WSGI entry point"
```

#### 10. `config/asgi.py`

```bash
git add config/asgi.py
git commit -m "chore(config): ASGI entry point"
```

## Stage 3 — App core: models, signing, throttle, migrations (commits 11–21)

#### 11. `polls/__init__.py`

```bash
git add polls/__init__.py
git commit -m "chore(polls): app package"
```

#### 12. `polls/apps.py`

```bash
git add polls/apps.py
git commit -m "chore(polls): app configuration"
```

#### 13. `polls/exceptions.py`

```bash
git add polls/exceptions.py
git commit -m "feat(polls): domain exceptions — PollClosed, AlreadyVoted, InvalidVote"
```

#### 14. `polls/signing.py`

```bash
git add polls/signing.py
git commit -m "feat(auth): signed anonymous voter tokens (TimestampSigner, max-age bound)"
```

#### 15. `polls/throttling.py`

```bash
git add polls/throttling.py
git commit -m "feat(security): cache-backed vote-attempt throttle (per IP + poll)"
```

#### 16. `polls/models.py`

```bash
git add polls/models.py
git commit -m "feat(models): Poll, Choice, Ballot, Vote with race-safe cast_vote()" -m "Single-choice and Borda-ranked voting, unique slugs via django-autoslug, optional expiry, owner-controlled result freezing. cast_vote() opens transaction.atomic(), locks the Poll row with select_for_update(), re-checks expiry/auth/already-voted inside the lock, locks the choices, then writes — so concurrent duplicates surface as the AlreadyVoted domain error, never a 500. Database-level partial unique constraints guarantee one ballot per (poll, user) and per (poll, voter_token)."
```

#### 17. `polls/migrations/__init__.py`

```bash
git add polls/migrations/__init__.py
git commit -m "chore(migrations): package"
```

#### 18. `polls/migrations/0001_initial.py`

```bash
git add polls/migrations/0001_initial.py
git commit -m "feat(db): initial schema — poll, choice, ballot, vote + partial unique constraints"
```

#### 19. `polls/migrations/0002_remove_poll_polls_poll_slug_3e2bd9_idx.py`

```bash
git add polls/migrations/0002_remove_poll_polls_poll_slug_3e2bd9_idx.py
git commit -m "chore(db): refine the poll.slug index (migration 0002)"
```

#### 20. `polls/migrations/0003_vote_vote_rank_null_or_positive.py`

```bash
git add polls/migrations/0003_vote_vote_rank_null_or_positive.py
git commit -m "feat(db): enforce vote.rank is null-or-positive in the database (CheckConstraint)"
```

#### 21. `polls/admin.py`

```bash
git add polls/admin.py
git commit -m "feat(admin): register Poll with inline choices, plus Ballot and Vote"
```

## Stage 4 — Middleware, tags, forms, views, URLs (commits 22–29)

#### 22. `polls/context_processors.py`

```bash
git add polls/context_processors.py
git commit -m "feat(templates): poll_settings and csp_nonce context processors"
```

#### 23. `polls/middleware.py`

```bash
git add polls/middleware.py
git commit -m "feat(security): CSP middleware — per-request nonce, strict headers, widget exemption" -m "Generates a per-request nonce injected into script-src (unsafe-inline is dropped when DEBUG is off), sends a strict default policy (default-src 'self', frame-ancestors 'none', base-uri 'none', form-action 'self'), and exempts only the widget path, which may be framed."
```

#### 24. `polls/templatetags/__init__.py`

```bash
git add polls/templatetags/__init__.py
git commit -m "chore: templatetags package"
```

#### 25. `polls/templatetags/poll_extras.py`

```bash
git add polls/templatetags/poll_extras.py
git commit -m "feat(templates): percentage_bar, pct, has_voted, message_alert tags" -m "percentage_bar takes the pre-computed total so result rendering never runs a per-choice aggregate (N+1 removed); message_alert decides the alert severity (highest wins, fallback info) and matching icon once instead of duplicating if/elif chains in templates."
```

#### 26. `polls/forms.py`

```bash
git add polls/forms.py
git commit -m "feat(forms): poll-create formset, dynamic vote forms, SignUpForm" -m "PollCreateForm (datetime-local expiry) paired with an inline ChoiceFormSet; small per-poll vote forms that adapt to single vs. ranked voting, with the actual write left to Poll.cast_vote(); and SignUpForm (username + email + Django's default password validators) for the registration page."
```

#### 27. `polls/urls.py`

```bash
git add polls/urls.py
git commit -m "feat(polls): app routes — home, create, detail, vote, results, widget, share, qr, freeze"
```

#### 28. `polls/views.py`

```bash
git add polls/views.py
git commit -m "feat(views): all class-based views, HTMX vote flow, registration" -m "HomeView (annotated counts, pagination, no N+1), PollCreateView with formset, detail page that swaps vote form / live results, VoteView that casts through the atomic cast_vote() and maps IntegrityError to the AlreadyVoted error before the HTMX partial swap plus the anon-token cookie hook, live results partial (3s hx-poll), full results page, iframe-safe widget, share page with QR PNG, owner-only freeze toggle, and SignUpView that signs the new account in immediately."
```

#### 29. `config/urls.py`

```bash
git add config/urls.py
git commit -m "feat(config): root URLs — signup route before the auth include, polls at root"
```

## Stage 5 — Seeding and tests (commits 30–33)

#### 30. `polls/management/__init__.py`

```bash
git add polls/management/__init__.py
git commit -m "chore: management package"
```

#### 31. `polls/management/commands/__init__.py`

```bash
git add polls/management/commands/__init__.py
git commit -m "chore: management commands package"
```

#### 32. `polls/management/commands/seed_polls.py`

```bash
git add polls/management/commands/seed_polls.py
git commit -m "feat(dev): idempotent seed_polls command (demo user + 5 demo polls)"
```

#### 33. `polls/tests.py`

```bash
git add polls/tests.py
git commit -m "test: 88-test suite — voting, tokens, concurrency, security, auth flows" -m "Covers single and ranked voting, the tamper-proof anon token, threaded concurrency (PostgreSQL-gated), cookie flags, CSP header + nonce regression, frame restrictions, freeze authorization (IDOR), the N+1 query-count invariant, the vote throttle, the message_alert tag, full create/vote/share/widget flows, and the auth stack: signup (render, create + auto sign-in, duplicate username, mismatched and weak passwords, authenticated redirect) and password reset/change journeys end to end."
```

## Stage 6 — Poll templates (commits 34–45)

#### 34. `polls/templates/polls/base.html`

```bash
git add polls/templates/polls/base.html
git commit -m "feat(ui): base layout — indigo palette, HTMX with SRI + nonce, header, messages" -m "Tailwind Play CDN with a custom brand (indigo) + ink (slate) palette on a soft slate page tint, Inter typeface, HTMX 1.9.12 loaded with an SRI integrity attribute and nonce'd inline config, central form-control styling (indigo focus ring, matching accent colors), header with POST sign-out, Sign up button and username linking to account settings, Django messages rendered through the message_alert tag, and a widget-aware layout that hides chrome inside the iframe."
```

#### 35. `polls/templates/polls/home.html`

```bash
git add polls/templates/polls/home.html
git commit -m "feat(ui): home page — gradient headline, paginated poll cards"
```

#### 36. `polls/templates/polls/poll_create.html`

```bash
git add polls/templates/polls/poll_create.html
git commit -m "feat(ui): create page — inline choice formset, nonce'd add-choice script"
```

#### 37. `polls/templates/polls/poll_detail.html`

```bash
git add polls/templates/polls/poll_detail.html
git commit -m "feat(ui): detail page — HTMX swap container for vote form vs. live results"
```

#### 38. `polls/templates/polls/poll_results_page.html`

```bash
git add polls/templates/polls/poll_results_page.html
git commit -m "feat(ui): full-page results view"
```

#### 39. `polls/templates/polls/poll_share.html`

```bash
git add polls/templates/polls/poll_share.html
git commit -m "feat(ui): share page — QR code, embed snippet, nonce'd copy-to-clipboard buttons"
```

#### 40. `polls/templates/polls/poll_widget.html`

```bash
git add polls/templates/polls/poll_widget.html
git commit -m "feat(ui): compact iframe-embeddable widget"
```

#### 41. `polls/templates/polls/partials/_bar.html`

```bash
git add polls/templates/polls/partials/_bar.html
git commit -m "feat(ui): result bar partial — animated fill, metric label, percentage"
```

#### 42. `polls/templates/polls/partials/_vote_form.html`

```bash
git add polls/templates/polls/partials/_vote_form.html
git commit -m "feat(ui): vote form partial — single/ranked UI, needs-login box with signup"
```

#### 43. `polls/templates/polls/partials/_results.html`

```bash
git add polls/templates/polls/partials/_results.html
git commit -m "feat(ui): live results partial — polls every 3s via HTMX"
```

#### 44. `polls/templates/polls/partials/_results_frozen.html`

```bash
git add polls/templates/polls/partials/_results_frozen.html
git commit -m "feat(ui): frozen-results placeholder — results hidden while voting stays open"
```

#### 45. `polls/templates/polls/partials/_message_alert.html`

```bash
git add polls/templates/polls/partials/_message_alert.html
git commit -m "feat(ui): message alert partial — severity class + icon from the message_alert tag"
```

## Stage 7 — Auth templates (commits 46–55)

#### 46. `templates/registration/signup.html`

```bash
git add templates/registration/signup.html
git commit -m "feat(auth): registration page — username, email, password with validator hints"
```

#### 47. `templates/registration/login.html`

```bash
git add templates/registration/login.html
git commit -m "feat(auth): login page — per-field errors, signup + forgot-password links"
```

#### 48. `templates/registration/logged_out.html`

```bash
git add templates/registration/logged_out.html
git commit -m "feat(auth): signed-out confirmation page"
```

#### 49. `templates/registration/password_change_form.html`

```bash
git add templates/registration/password_change_form.html
git commit -m "feat(auth): change-password form (current + new password)"
```

#### 50. `templates/registration/password_change_done.html`

```bash
git add templates/registration/password_change_done.html
git commit -m "feat(auth): change-password success page"
```

#### 51. `templates/registration/password_reset_form.html`

```bash
git add templates/registration/password_reset_form.html
git commit -m "feat(auth): request-password-reset form (email)"
```

#### 52. `templates/registration/password_reset_done.html`

```bash
git add templates/registration/password_reset_done.html
git commit -m "feat(auth): reset-email-sent page (notes the console backend for dev)"
```

#### 53. `templates/registration/password_reset_confirm.html`

```bash
git add templates/registration/password_reset_confirm.html
git commit -m "feat(auth): set-new-password page with invalid/expired-link fallback"
```

#### 54. `templates/registration/password_reset_complete.html`

```bash
git add templates/registration/password_reset_complete.html
git commit -m "feat(auth): password-set success page"
```

#### 55. `templates/registration/password_reset_email.html`

```bash
git add templates/registration/password_reset_email.html
git commit -m "feat(auth): password-reset email body with protocol/domain-aware reset link"
```

## Stage 8 — Static dirs and documentation (commits 56–59)

#### 56. `static/css/.gitkeep`

```bash
git add static/css/.gitkeep
git commit -m "chore(static): keep css dir for collectstatic output"
```

#### 57. `static/js/.gitkeep`

```bash
git add static/js/.gitkeep
git commit -m "chore(static): keep js dir for collectstatic output"
```

#### 58. `README.md`

```bash
git add README.md
git commit -m "docs: full README — architecture, schema, security, distinctions, routes, limits"
```

#### 59. `COMMITS.md`

```bash
git add COMMITS.md
git commit -m "docs: 10-commit logical plan as an alternative way to stage this history"
```

---

## After the 59 commits — push to GitHub

```bash
git remote add origin git@github.com:<you>/<repo>.git
git push -u origin main
```

## Verify the pushed state

```bash
python manage.py check            # 0 issues
python manage.py test polls       # 88 tests: 87 pass, 1 skipped (Postgres-only)
git log --oneline                 # 59 commits, oldest = .gitignore
```
