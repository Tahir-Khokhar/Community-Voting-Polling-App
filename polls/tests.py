"""Test suite for the polls app.

Covers the core voting mechanics (single + ranked), the tamper-proof anonymous
token, the race-safe counter updates (including the IntegrityError -> AlreadyVoted
fallback), and the main view flows. Run with ``python manage.py test polls``.
"""

from datetime import timedelta
import re
import threading
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages import constants as message_constants
from django.contrib.messages.storage.base import Message
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, close_old_connections, transaction
from django.template import Context, Template
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .admin import BallotAdmin, ChoiceAdmin, ChoiceInline, PollAdmin, VoteAdmin
from .exceptions import AlreadyVoted, InvalidVote, PollClosed, RateLimited
from .models import Ballot, Choice, Poll, Vote
from .signing import cookie_name, mint_voter_token, verify_voter_token
from .templatetags.poll_extras import pct
from .throttling import vote_attempt_allowed


def make_poll(title="Test poll", poll_type="single", voting_mode="anonymous",
              n_choices=3, **kwargs):
    """Factory: create a poll with ``n_choices`` choices."""
    poll = Poll.objects.create(
        title=title, poll_type=poll_type, voting_mode=voting_mode, **kwargs
    )
    Choice.objects.bulk_create(
        [Choice(poll=poll, text=f"Choice {i}", order=i) for i in range(n_choices)]
    )
    return poll


# ---------------------------------------------------------------------------
# Poll status & visibility helpers
# ---------------------------------------------------------------------------
class PollStatusTests(TestCase):
    def setUp(self):
        self.poll = make_poll()

    def test_active_when_no_expiry(self):
        self.assertTrue(self.poll.is_active)
        self.assertFalse(self.poll.is_expired)

    def test_expired_when_expiry_in_past(self):
        self.poll.expires_at = timezone.now() - timedelta(hours=1)
        self.poll.save()
        self.assertTrue(self.poll.is_expired)
        self.assertFalse(self.poll.is_active)

    def test_not_expired_when_expiry_in_future(self):
        self.poll.expires_at = timezone.now() + timedelta(hours=1)
        self.poll.save()
        self.assertFalse(self.poll.is_expired)

    def test_results_visible_by_default(self):
        self.assertTrue(self.poll.results_visible(user=None))

    def test_results_hidden_when_frozen(self):
        self.poll.results_frozen = True
        self.poll.save()
        self.assertFalse(self.poll.results_visible(user=None))

    def test_results_visible_to_owner_when_frozen(self):
        owner = User.objects.create_user("owner", password="x")
        self.poll.created_by = owner
        self.poll.results_frozen = True
        self.poll.save()
        self.assertTrue(self.poll.results_visible(user=owner))

    def test_results_visible_to_superuser_when_frozen(self):
        admin = User.objects.create_superuser("admin", password="x", email="a@a")
        self.poll.results_frozen = True
        self.poll.save()
        self.assertTrue(self.poll.results_visible(user=admin))

    def test_empty_poll_has_zero_totals(self):
        self.assertEqual(self.poll.total_votes(), 0)
        self.assertEqual(self.poll.total_ballots(), 0)


# ---------------------------------------------------------------------------
# Single-choice voting
# ---------------------------------------------------------------------------
class SingleVoteTests(TestCase):
    def setUp(self):
        self.poll = make_poll(n_choices=3)
        self.choice = self.poll.choices.first()

    def test_cast_vote_increments_counter(self):
        ballot = self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        self.assertEqual(ballot.voter_token, "tok-1")
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)
        self.assertEqual(self.poll.total_votes(), 1)

    def test_same_token_cannot_vote_twice(self):
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        with self.assertRaises(AlreadyVoted):
            self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)

    def test_distinct_tokens_each_count(self):
        for i in range(3):
            self.poll.cast_vote(voter_token=f"tok-{i}", choice_id=self.choice.id)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 3)
        self.assertEqual(self.poll.total_ballots(), 3)

    def test_invalid_choice_id_rejected(self):
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="tok-1", choice_id=999999)

    def test_missing_choice_rejected(self):
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="tok-1", choice_id=None)

    def test_expired_poll_rejects_vote(self):
        self.poll.expires_at = timezone.now() - timedelta(minutes=5)
        self.poll.save()
        with self.assertRaises(PollClosed):
            self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)

    def test_anonymous_poll_requires_token(self):
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="", choice_id=self.choice.id)


# ---------------------------------------------------------------------------
# Ranked-choice voting (Borda)
# ---------------------------------------------------------------------------
class RankedVoteTests(TestCase):
    def setUp(self):
        self.poll = make_poll(poll_type="ranked", n_choices=3)
        self.ids = list(self.poll.choices.values_list("id", flat=True))

    def test_borda_scores_assigned_correctly(self):
        # rank 1 -> 3 pts, rank 2 -> 2 pts, rank 3 -> 1 pt
        rankings = {self.ids[0]: 1, self.ids[1]: 2, self.ids[2]: 3}
        self.poll.cast_vote(voter_token="tok-1", rankings=rankings)
        c1, c2, c3 = (self.poll.choices.get(id=cid) for cid in self.ids)
        self.assertEqual(c1.borda_score, 3)
        self.assertEqual(c2.borda_score, 2)
        self.assertEqual(c3.borda_score, 1)
        self.assertEqual(c1.vote_count, 1)  # first-place vote
        self.assertEqual(self.poll.total_votes(), 6)  # 3 + 2 + 1

    def test_missing_choice_rank_rejected(self):
        rankings = {self.ids[0]: 1, self.ids[1]: 2}
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="tok-1", rankings=rankings)

    def test_duplicate_ranks_rejected(self):
        rankings = {self.ids[0]: 1, self.ids[1]: 1, self.ids[2]: 2}
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="tok-1", rankings=rankings)

    def test_rank_gap_rejected(self):
        rankings = {self.ids[0]: 1, self.ids[1]: 3, self.ids[2]: 4}
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="tok-1", rankings=rankings)

    def test_ranked_double_vote_blocked(self):
        rankings = {self.ids[0]: 1, self.ids[1]: 2, self.ids[2]: 3}
        self.poll.cast_vote(voter_token="tok-1", rankings=rankings)
        with self.assertRaises(AlreadyVoted):
            self.poll.cast_vote(voter_token="tok-1", rankings=rankings)


# ---------------------------------------------------------------------------
# Authenticated polls
# ---------------------------------------------------------------------------
class AuthenticatedPollTests(TestCase):
    def setUp(self):
        self.poll = make_poll(voting_mode="authenticated", n_choices=2)
        self.user = User.objects.create_user("alice", password="secret")
        self.choice = self.poll.choices.first()

    def test_anonymous_rejected_on_auth_poll(self):
        with self.assertRaises(InvalidVote):
            self.poll.cast_vote(voter_token="tok", choice_id=self.choice.id)

    def test_authenticated_user_can_vote(self):
        ballot = self.poll.cast_vote(user=self.user, choice_id=self.choice.id)
        self.assertEqual(ballot.user, self.user)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)

    def test_same_user_cannot_vote_twice(self):
        self.poll.cast_vote(user=self.user, choice_id=self.choice.id)
        with self.assertRaises(AlreadyVoted):
            self.poll.cast_vote(user=self.user, choice_id=self.choice.id)

    def test_different_users_can_each_vote(self):
        bob = User.objects.create_user("bob", password="secret")
        self.poll.cast_vote(user=self.user, choice_id=self.choice.id)
        self.poll.cast_vote(user=bob, choice_id=self.choice.id)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 2)


# ---------------------------------------------------------------------------
# Race safety: the unique constraint is the real guard
# ---------------------------------------------------------------------------
class RaceSafetyTests(TestCase):
    def test_concurrent_double_vote_raises_already_voted_not_500(self):
        """If has_voted() misses a concurrent insert, the unique constraint
        catches it and we translate IntegrityError into AlreadyVoted."""
        poll = make_poll(n_choices=2)
        choice = poll.choices.first()
        poll.cast_vote(voter_token="tok-1", choice_id=choice.id)
        # Simulate the race: pretend has_voted doesn't see the existing ballot.
        with patch.object(Poll, "has_voted", return_value=False):
            with self.assertRaises(AlreadyVoted):
                poll.cast_vote(voter_token="tok-1", choice_id=choice.id)
        self.assertEqual(Ballot.objects.filter(poll=poll).count(), 1)


# ---------------------------------------------------------------------------
# Token signing
# ---------------------------------------------------------------------------
class TokenSigningTests(TestCase):
    def test_minted_token_verifies(self):
        token = mint_voter_token(poll_id=42)
        self.assertIsNotNone(verify_voter_token(token, poll_id=42))

    def test_token_wrong_poll_rejected(self):
        token = mint_voter_token(poll_id=42)
        self.assertIsNone(verify_voter_token(token, poll_id=99))

    def test_garbage_token_rejected(self):
        self.assertIsNone(verify_voter_token("not-a-real-token", poll_id=42))

    def test_empty_token_rejected(self):
        self.assertIsNone(verify_voter_token("", poll_id=42))

    def test_cookie_name_scoped_per_poll(self):
        self.assertEqual(cookie_name(1), "poll_voter_1")
        self.assertNotEqual(cookie_name(1), cookie_name(2))


# ---------------------------------------------------------------------------
# Template tag
# ---------------------------------------------------------------------------
class PctTagTests(TestCase):
    def test_simple_percentage(self):
        self.assertEqual(pct(3, 10), 30)

    def test_zero_total_returns_zero(self):
        self.assertEqual(pct(5, 0), 0)

    def test_rounds_to_nearest(self):
        self.assertEqual(pct(2, 3), 67)

    def test_full_total(self):
        self.assertEqual(pct(10, 10), 100)


# ---------------------------------------------------------------------------
# Views (HTTP flow)
# ---------------------------------------------------------------------------
class ViewTests(TestCase):
    def setUp(self):
        self.poll = make_poll(n_choices=2)
        self.choice = self.poll.choices.first()

    def test_home_lists_polls(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.poll.title)

    def test_detail_sets_voter_cookie_for_anonymous_poll(self):
        resp = self.client.get(f"/{self.poll.slug}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(cookie_name(self.poll.id), resp.cookies)

    def test_detail_404_for_unknown_slug(self):
        resp = self.client.get("/no-such-poll/")
        self.assertEqual(resp.status_code, 404)

    def test_vote_post_records_vote(self):
        resp = self.client.post(
            f"/{self.poll.slug}/vote/", {"choice": self.choice.id}
        )
        self.assertEqual(resp.status_code, 200)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)
        self.assertEqual(Ballot.objects.count(), 1)

    def test_stored_voter_token_fits_field_max_length(self):
        """Regression: the view flow must store the short voter id (16 hex
        chars) on Ballot.voter_token, NOT the full signed token. The signed
        blob is ~70 chars and exceeds the field's max_length=64 — silently
        tolerated by SQLite but a hard DataError on PostgreSQL/MySQL."""
        self.client.post(f"/{self.poll.slug}/vote/", {"choice": self.choice.id})
        ballot = Ballot.objects.get()
        max_length = Ballot._meta.get_field("voter_token").max_length
        self.assertLessEqual(
            len(ballot.voter_token), max_length,
            f"stored voter_token is {len(ballot.voter_token)} chars, "
            f"field max_length is {max_length}",
        )
        # The voter id is 16 hex chars with no separators; the signed blob
        # contains ":" separators and is ~70 chars.
        self.assertEqual(len(ballot.voter_token), 16)
        self.assertNotIn(":", ballot.voter_token)

    def test_double_vote_does_not_add_second_ballot(self):
        self.client.post(f"/{self.poll.slug}/vote/", {"choice": self.choice.id})
        # The test client preserves the voter cookie, so the second POST is
        # recognised as a repeat and rejected at the ballot layer.
        self.client.post(f"/{self.poll.slug}/vote/", {"choice": self.choice.id})
        self.assertEqual(Ballot.objects.count(), 1)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)

    def test_results_partial_responds(self):
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        resp = self.client.get(f"/{self.poll.slug}/results/")
        self.assertEqual(resp.status_code, 200)

    def test_results_html_contains_no_template_comment(self):
        # Regression: a multi-line {# ... #} comment used to leak its text to
        # voters above the result bars — Django's {# #} only works on a single
        # line, so the raw comment was rendered. Multi-line comments must use
        # {% comment %}...{% endcomment %}.
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        for url in (f"/{self.poll.slug}/results/", f"/{self.poll.slug}/results-page/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertNotIn(b"{#", resp.content)
            self.assertNotIn(b"Compute the aggregate totals", resp.content)

    def test_favicon_redirects_to_static_asset(self):
        # Regression: /favicon.ico used to 404 on every page.
        resp = self.client.get("/favicon.ico")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/static/favicon.ico")

    def test_qr_endpoint_returns_png(self):
        resp = self.client.get(f"/{self.poll.slug}/qr.png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")

    def test_create_requires_login(self):
        resp = self.client.get("/create/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_results_page_renders(self):
        resp = self.client.get(f"/{self.poll.slug}/results-page/")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Security: anonymous voter cookie flags + token/cookie lifetime alignment
# ---------------------------------------------------------------------------
class AnonymousCookieTests(TestCase):
    def setUp(self):
        self.poll = make_poll(n_choices=2)

    def test_cookie_max_age_does_not_exceed_token_max_age(self):
        # The cookie must not outlive the signed token inside it, otherwise an
        # expired token + live cookie lets a visitor be minted a fresh token
        # and vote again within the cookie's life.
        self.assertLessEqual(
            settings.POLL_SETTINGS["ANON_COOKIE_MAX_AGE"],
            settings.POLL_SETTINGS["ANON_TOKEN_MAX_AGE"],
        )

    def test_detail_sets_httponly_lax_cookie(self):
        resp = self.client.get(f"/{self.poll.slug}/")
        c = resp.cookies[cookie_name(self.poll.id)]
        self.assertTrue(c["httponly"])
        self.assertEqual(c["samesite"], "Lax")

    def test_cookie_max_age_matches_setting(self):
        resp = self.client.get(f"/{self.poll.slug}/")
        c = resp.cookies[cookie_name(self.poll.id)]
        self.assertEqual(int(c["max-age"]), settings.POLL_SETTINGS["ANON_COOKIE_MAX_AGE"])

    @override_settings(DEBUG=True)
    def test_cookie_not_secure_in_dev(self):
        # DEBUG=True -> Secure=False so the browser sets the cookie over plain
        # HTTP during local development.
        resp = self.client.get(f"/{self.poll.slug}/")
        self.assertFalse(resp.cookies[cookie_name(self.poll.id)]["secure"])

    @override_settings(DEBUG=False)
    def test_cookie_marked_secure_in_production(self):
        # DEBUG=False -> Secure=True so the cookie is never leaked over HTTP.
        resp = self.client.get(f"/{self.poll.slug}/")
        self.assertTrue(resp.cookies[cookie_name(self.poll.id)]["secure"])


# ---------------------------------------------------------------------------
# Security: CSP header, nonce, and frame restrictions
# ---------------------------------------------------------------------------
class SecurityHeadersTests(TestCase):
    def setUp(self):
        self.poll = make_poll(n_choices=2)

    def test_csp_header_present_with_nonce(self):
        resp = self.client.get("/")
        csp = resp["Content-Security-Policy"]
        self.assertIn("script-src", csp)
        # A per-request nonce is injected so inline scripts can run without a
        # blanket 'unsafe-inline'.
        self.assertIn("'nonce-", csp)

    @override_settings(DEBUG=True)
    def test_csp_unsafe_inline_kept_in_dev(self):
        # DEBUG=True -> 'unsafe-inline' retained for dev convenience. A nonce
        # takes precedence over 'unsafe-inline' per the CSP spec, so the nonce
        # still governs inline scripts.
        resp = self.client.get("/")
        script_src = resp["Content-Security-Policy"].split("script-src")[1].split(";")[0]
        self.assertIn("'unsafe-inline'", script_src)

    @override_settings(DEBUG=False)
    def test_csp_unsafe_inline_dropped_in_production(self):
        resp = self.client.get("/")
        script_src = resp["Content-Security-Policy"].split("script-src")[1].split(";")[0]
        self.assertNotIn("'unsafe-inline'", script_src)
        self.assertIn("'nonce-", script_src)

    def test_normal_page_denies_framing(self):
        resp = self.client.get(f"/{self.poll.slug}/")
        self.assertEqual(resp["X-Frame-Options"], "DENY")
        fa = resp["Content-Security-Policy"].split("frame-ancestors")[1].split(";")[0]
        self.assertIn("'none'", fa)

    def test_widget_allows_framing(self):
        resp = self.client.get(f"/{self.poll.slug}/widget/")
        # xframe_options_exempt -> no legacy X-Frame-Options header on widget.
        self.assertNotIn("X-Frame-Options", resp)
        fa = resp["Content-Security-Policy"].split("frame-ancestors")[1].split(";")[0]
        self.assertIn("*", fa)

    def test_other_security_headers(self):
        resp = self.client.get("/")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn("geolocation=()", resp["Permissions-Policy"])


# ---------------------------------------------------------------------------
# Authorization: only the owner / a superuser may freeze results
# ---------------------------------------------------------------------------
class FreezeAuthorizationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="secret")
        self.poll = make_poll(n_choices=2)
        self.poll.created_by = self.owner
        self.poll.save()

    def test_anonymous_redirected_to_login(self):
        resp = self.client.post(f"/{self.poll.slug}/freeze/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])
        self.poll.refresh_from_db()
        self.assertFalse(self.poll.results_frozen)

    def test_non_owner_cannot_freeze(self):
        other = User.objects.create_user("other", password="secret")
        self.client.force_login(other)
        resp = self.client.post(f"/{self.poll.slug}/freeze/")
        self.assertEqual(resp.status_code, 302)
        self.poll.refresh_from_db()
        self.assertFalse(self.poll.results_frozen)  # state unchanged

    def test_owner_can_freeze(self):
        self.client.force_login(self.owner)
        resp = self.client.post(f"/{self.poll.slug}/freeze/")
        self.assertEqual(resp.status_code, 302)
        self.poll.refresh_from_db()
        self.assertTrue(self.poll.results_frozen)

    def test_superuser_can_freeze(self):
        admin = User.objects.create_superuser("admin", password="x", email="a@a")
        self.client.force_login(admin)
        resp = self.client.post(f"/{self.poll.slug}/freeze/")
        self.assertEqual(resp.status_code, 302)
        self.poll.refresh_from_db()
        self.assertTrue(self.poll.results_frozen)


# ---------------------------------------------------------------------------
# Performance: the results partial must not run per-choice queries (no N+1)
# ---------------------------------------------------------------------------
class ResultsQueryCountTests(TestCase):
    def _count_queries(self, n_choices):
        poll = make_poll(n_choices=n_choices)
        choices = list(poll.choices.all())
        poll.cast_vote(voter_token="tok-1", choice_id=choices[0].id)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(f"/{poll.slug}/results/")
        self.assertEqual(resp.status_code, 200)
        return len(ctx.captured_queries)

    def test_query_count_does_not_scale_with_choices(self):
        # The defining property of "no N+1": increasing the choice count must
        # not increase the query count. Before the fix the results partial ran
        # an aggregate + a choice.poll lookup per choice (~2 queries/choice).
        small = self._count_queries(3)
        large = self._count_queries(8)
        self.assertEqual(
            small, large,
            f"query count grew with choice count ({small} -> {large}); N+1 present.",
        )


# ---------------------------------------------------------------------------
# Throttle: per-IP+poll vote-attempt abuse brake
# ---------------------------------------------------------------------------
class ThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def _req(self, ip="1.2.3.4"):
        req = self.factory.get("/")
        req.META["REMOTE_ADDR"] = ip
        return req

    def test_allows_up_to_limit_then_blocks(self):
        limit = settings.POLL_SETTINGS["VOTE_THROTTLE_MAX_ATTEMPTS"]
        for _ in range(limit):
            self.assertTrue(vote_attempt_allowed(self._req(), poll_id=1))
        # The (limit+1)th attempt within the same window is blocked.
        self.assertFalse(vote_attempt_allowed(self._req(), poll_id=1))

    def test_distinct_polls_and_ips_tracked_separately(self):
        limit = settings.POLL_SETTINGS["VOTE_THROTTLE_MAX_ATTEMPTS"]
        for _ in range(limit):
            self.assertTrue(vote_attempt_allowed(self._req("1.1.1.1"), poll_id=1))
        # Same IP, different poll -> separate counter, still allowed.
        self.assertTrue(vote_attempt_allowed(self._req("1.1.1.1"), poll_id=2))
        # Different IP, same poll -> still allowed.
        self.assertTrue(vote_attempt_allowed(self._req("2.2.2.2"), poll_id=1))


# ---------------------------------------------------------------------------
# Concurrency: real threads voting on the same poll + token at once.
#
# TransactionTestCase (not TestCase) so each thread's writes truly commit to
# the database rather than being rolled back inside the test's outer
# transaction. On SQLite the database-level write lock serialises the threads;
# on PostgreSQL the select_for_update() row locks + the unique_ballot_per_token
# constraint serialise them. Both backends must end with exactly one ballot.
#
# NOTE: this proves no double ballot under concurrency on whichever database
# the suite is run against. To exercise real PostgreSQL row locking, run the
# suite against a Postgres DB (see README "Testing" -> PostgreSQL).
# ---------------------------------------------------------------------------
class ConcurrentVoteTests(TransactionTestCase):
    def setUp(self):
        # SQLite raises SQLITE_LOCKED on concurrent writes to the same table,
        # and the busy-timeout does NOT retry table-level locks (only
        # database-level SQLITE_BUSY). So this real-concurrency test runs only
        # under PostgreSQL, whose select_for_update() row locks + the
        # unique_ballot_per_token constraint are what it is meant to exercise.
        # The race *logic* is covered on every backend by RaceSafetyTests.
        # See README "Testing" -> PostgreSQL for how to run this suite against
        # a Postgres database.
        if connection.vendor != "postgresql":
            self.skipTest("real concurrent-writer test requires PostgreSQL "
                          "(SQLite raises SQLITE_LOCKED on concurrent writes)")

    def test_concurrent_same_token_yields_single_ballot(self):
        poll = make_poll(n_choices=2)
        choice = poll.choices.first()
        token = "concurrent-token"
        unexpected = []

        def voter():
            try:
                # Each thread uses its own connection (Django opens one lazily
                # per thread); close_old_connections keeps the pool clean.
                poll.cast_vote(voter_token=token, choice_id=choice.id)
            except AlreadyVoted:
                pass  # expected for every thread except the winner
            except Exception as exc:  # pragma: no cover - defensive
                unexpected.append(repr(exc))
            finally:
                close_old_connections()

        threads = [threading.Thread(target=voter) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(unexpected, [], f"unexpected errors: {unexpected}")
        self.assertEqual(Ballot.objects.filter(poll=poll).count(), 1)
        choice.refresh_from_db()
        self.assertEqual(choice.vote_count, 1)


# ---------------------------------------------------------------------------
# Messages: the {% message_alert %} tag + the freeze-flow alerts
# ---------------------------------------------------------------------------
class MessageAlertTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="secret")
        self.poll = make_poll(n_choices=2)
        self.poll.created_by = self.owner
        self.poll.save()

    def test_tag_renders_correct_class_per_severity(self):
        tpl = Template("{% load poll_extras %}{% message_alert m %}")
        cases = {
            message_constants.ERROR: "border-red-400/30 bg-red-500/10 text-red-300",
            message_constants.WARNING: "border-amber-400/30 bg-amber-500/10 text-amber-300",
            message_constants.SUCCESS: "border-emerald-400/30 bg-emerald-500/10 text-emerald-300",
            message_constants.INFO: "border-brand-400/30 bg-brand-500/10 text-brand-700",
        }
        for level, css in cases.items():
            out = tpl.render(Context({"m": Message(level, "hello")}))
            self.assertIn(css, out, f"severity {level} did not render {css}")
            self.assertIn("hello", out)  # the message text is rendered
            self.assertIn("<svg", out)   # an icon is always rendered

    def test_tag_highest_severity_wins(self):
        # A message carrying both error and warning tags reports as error.
        tpl = Template("{% load poll_extras %}{% message_alert m %}")
        m = Message(message_constants.ERROR, "boom", extra_tags="warning")
        out = tpl.render(Context({"m": m}))
        self.assertIn("border-red-400/30", out)
        self.assertNotIn("border-amber-400/30", out)

    def test_owner_freeze_renders_success_alert(self):
        self.client.force_login(self.owner)
        resp = self.client.post(f"/{self.poll.slug}/freeze/", follow=True)
        self.assertContains(resp, "Results frozen.")
        self.assertContains(resp, "border-emerald-400/30 bg-emerald-500/10 text-emerald-300")

    def test_non_owner_freeze_renders_error_alert(self):
        other = User.objects.create_user("other", password="secret")
        self.client.force_login(other)
        resp = self.client.post(f"/{self.poll.slug}/freeze/", follow=True)
        self.assertContains(resp, "Only the poll owner can freeze results.")
        self.assertContains(resp, "border-red-400/30 bg-red-500/10 text-red-300")


# ---------------------------------------------------------------------------
# Full flows: the create formset flow, ranked voting over HTTP, share/widget
# pages, auth views, the seed command, and admin — paths the targeted unit
# tests above don't exercise end-to-end.
# ---------------------------------------------------------------------------
class FullFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("creator", password="secret")
        self.client.force_login(self.user)

    def _formset_data(self, texts):
        from .forms import ChoiceFormSet
        prefix = ChoiceFormSet().prefix
        data = {
            f"{prefix}-TOTAL_FORMS": str(len(texts)),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        }
        for i, text in enumerate(texts):
            data[f"{prefix}-{i}-text"] = text
        return data

    def test_create_page_renders_for_logged_in(self):
        resp = self.client.get("/create/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create a poll")
        self.assertContains(resp, "-TOTAL_FORMS")  # choice formset management form

    def test_create_post_creates_poll_with_choices(self):
        data = {
            "title": "HTTP created poll",
            "description": "made through the form",
            "poll_type": "single",
            "voting_mode": "anonymous",
            "expires_at": "",
            **self._formset_data(["Alpha", "Beta"]),
        }
        resp = self.client.post("/create/", data)
        self.assertRedirects(resp, "/")
        poll = Poll.objects.get(title="HTTP created poll")
        self.assertEqual(poll.created_by, self.user)
        self.assertEqual(
            list(poll.choices.values_list("text", flat=True)), ["Alpha", "Beta"]
        )
        self.assertEqual([c.order for c in poll.choices.order_by("order")], [0, 1])

    def test_create_post_with_one_choice_is_rejected(self):
        data = {
            "title": "Bad poll", "poll_type": "single", "voting_mode": "anonymous",
            "expires_at": "",
            **self._formset_data(["Only one"]),
        }
        resp = self.client.post("/create/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Poll.objects.filter(title="Bad poll").exists())
        self.assertContains(resp, "Please submit at least")

    def test_create_post_past_expiry_is_rejected(self):
        data = {
            "title": "Past poll", "poll_type": "single", "voting_mode": "anonymous",
            "expires_at": "2020-01-01T00:00",
            **self._formset_data(["A", "B"]),
        }
        resp = self.client.post("/create/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Poll.objects.filter(title="Past poll").exists())
        self.assertContains(resp, "Expiry must be in the future.")

    def test_ranked_vote_over_http(self):
        poll = make_poll(poll_type="ranked", n_choices=3)
        ids = list(poll.choices.values_list("id", flat=True))
        data = {f"choice_{cid}": str(rank) for cid, rank in zip(ids, [1, 2, 3], strict=False)}
        resp = self.client.post(f"/{poll.slug}/vote/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ranked results (Borda score)")
        first = poll.choices.get(id=ids[0])
        first.refresh_from_db()
        self.assertEqual(first.borda_score, 3)  # rank 1 of 3 -> 3 points
        self.assertEqual(first.vote_count, 1)   # + the first-place vote
        self.assertEqual(Ballot.objects.filter(poll=poll).count(), 1)

    def test_share_page_shows_links_and_qr(self):
        poll = make_poll()
        resp = self.client.get(f"/{poll.slug}/share/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"/{poll.slug}/widget/")
        self.assertContains(resp, "qr.png")
        self.assertContains(resp, "Copy embed")

    def test_widget_page_renders_and_exempts_framing(self):
        poll = make_poll()
        resp = self.client.get(f"/{poll.slug}/widget/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("X-Frame-Options", resp)

    def test_inline_scripts_carry_csp_nonce(self):
        # Regression: the create/share pages' inline scripts MUST carry the
        # per-request nonce — production CSP drops 'unsafe-inline' from
        # script-src, so a nonce-less inline script is blocked and the
        # add-choice / copy buttons silently die.
        resp = self.client.get("/create/")
        self.assertIn('nonce="', resp.content.decode())
        poll = make_poll()
        resp = self.client.get(f"/{poll.slug}/share/")
        self.assertRegex(resp.content.decode(), r'<script nonce="[^"]+">')

    def test_login_logout_flow(self):
        self.client.logout()
        resp = self.client.get("/accounts/login/")
        self.assertEqual(resp.status_code, 200)
        # Bad credentials -> the non-field error is rendered.
        resp = self.client.post(
            "/accounts/login/", {"username": "creator", "password": "wrong"}
        )
        self.assertContains(resp, "Please enter a correct")
        # Empty fields -> per-field errors are rendered (regression: the
        # template used to render only non-field errors, so empty submits
        # showed nothing at all).
        resp = self.client.post("/accounts/login/", {})
        self.assertContains(resp, "This field is required")
        # Good credentials -> redirect to home, signed in.
        resp = self.client.post(
            "/accounts/login/", {"username": "creator", "password": "secret"}
        )
        self.assertRedirects(resp, "/")
        # Sign out (POST — LogoutView rejects GET since Django 5.0).
        resp = self.client.post("/accounts/logout/")
        self.assertRedirects(resp, "/")

    def test_logout_rejects_get(self):
        # Regression: the header used to sign out via a GET link, which 405s.
        resp = self.client.get("/accounts/logout/")
        self.assertEqual(resp.status_code, 405)

    def test_seed_command_is_idempotent(self):
        from io import StringIO
        from django.core.management import call_command

        out1, out2 = StringIO(), StringIO()
        # Seeding is allowed only while DEBUG is on (dev context) — declare it
        # explicitly, since the test runner itself runs with DEBUG=False.
        with override_settings(DEBUG=True):
            call_command("seed_polls", stdout=out1)
            call_command("seed_polls", stdout=out2)
        self.assertIn("Created demo user", out1.getvalue())
        self.assertEqual(Poll.objects.count(), 5)
        # Re-running skips every poll instead of duplicating them.
        self.assertIn("skipped 5 existing", out2.getvalue())
        self.assertEqual(Poll.objects.count(), 5)

    def test_seed_command_refuses_when_debug_off(self):
        # The demo superuser has known credentials — production (DEBUG off)
        # must refuse to create it.
        from io import StringIO

        out = StringIO()
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("seed_polls", stdout=out)
        self.assertEqual(Poll.objects.count(), 0)

    def test_admin_pages_load(self):
        User.objects.create_superuser("admin", "admin@example.com", password="secret")
        self.client.force_login(User.objects.get(username="admin"))
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertEqual(self.client.get("/admin/polls/poll/").status_code, 200)
        self.assertEqual(self.client.get("/admin/polls/poll/add/").status_code, 200)


# ---------------------------------------------------------------------------
# Registration (signup) — the page that was missing from the project
# ---------------------------------------------------------------------------
class SignUpTests(TestCase):
    def test_signup_page_renders(self):
        resp = self.client.get("/accounts/signup/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create your account")
        self.assertContains(resp, "Username")
        self.assertContains(resp, "Email")

    def test_signup_creates_user_and_logs_in(self):
        data = {
            "username": "newuser",
            "email": "new@example.com",
            "password1": "sUp3r-secret-pass",
            "password2": "sUp3r-secret-pass",
        }
        resp = self.client.post("/accounts/signup/", data, follow=True)
        user = User.objects.get(username="newuser")
        self.assertEqual(user.email, "new@example.com")
        # The new account is signed in immediately and greeted on the home page.
        self.assertContains(resp, "Welcome, newuser")
        self.assertTrue(resp.context["user"].is_authenticated)

    def test_signup_duplicate_username_rejected(self):
        User.objects.create_user("taken", password="x")
        data = {
            "username": "taken", "email": "t@example.com",
            "password1": "sUp3r-secret-pass", "password2": "sUp3r-secret-pass",
        }
        resp = self.client.post("/accounts/signup/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
        self.assertEqual(User.objects.filter(username="taken").count(), 1)

    def test_signup_password_mismatch_rejected(self):
        data = {
            "username": "mismatch", "email": "m@example.com",
            "password1": "sUp3r-secret-pass", "password2": "different-pass-1",
        }
        resp = self.client.post("/accounts/signup/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="mismatch").exists())

    def test_signup_weak_password_rejected(self):
        data = {
            "username": "weakpw", "email": "w@example.com",
            "password1": "password", "password2": "password",
        }
        resp = self.client.post("/accounts/signup/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="weakpw").exists())

    def test_signup_redirects_authenticated_users(self):
        self.client.force_login(User.objects.create_user("logged", password="x"))
        resp = self.client.get("/accounts/signup/")
        self.assertRedirects(resp, "/")


# ---------------------------------------------------------------------------
# Password reset + change — auth URLs existed but had no templates (would 500)
# ---------------------------------------------------------------------------
class PasswordFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "resetme", email="reset@example.com", password="old-pass-123"
        )

    def test_password_reset_end_to_end(self):
        self.assertEqual(self.client.get("/accounts/password_reset/").status_code, 200)
        resp = self.client.post(
            "/accounts/password_reset/", {"email": "reset@example.com"}
        )
        self.assertRedirects(resp, "/accounts/password_reset/done/")
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"/accounts/reset/([\w-]+)/([\w-]+)/", mail.outbox[0].body)
        self.assertIsNotNone(match, "reset link missing from the email body")
        uid, token = match.groups()
        # Valid token -> internal redirect to the set-password form.
        resp = self.client.get(f"/accounts/reset/{uid}/{token}/", follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Choose a new password")
        set_path = resp.request["PATH_INFO"]
        resp = self.client.post(
            set_path,
            {"new_password1": "brand-new-pass-9", "new_password2": "brand-new-pass-9"},
        )
        self.assertRedirects(resp, "/accounts/reset/done/")
        # The old password is gone; the new one signs in.
        self.assertFalse(self.client.login(username="resetme", password="old-pass-123"))
        self.assertTrue(self.client.login(username="resetme", password="brand-new-pass-9"))

    def test_password_change_flow(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/accounts/password_change/").status_code, 200)
        resp = self.client.post(
            "/accounts/password_change/",
            {
                "old_password": "old-pass-123",
                "new_password1": "fresh-pass-456",
                "new_password2": "fresh-pass-456",
            },
        )
        self.assertRedirects(resp, "/accounts/password_change/done/")
        self.assertTrue(self.client.login(username="resetme", password="fresh-pass-456"))

    def test_password_change_requires_login(self):
        resp = self.client.get("/accounts/password_change/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])


# ---------------------------------------------------------------------------
# Counter integrity: ballots survive user deletion, recount repairs drift,
# the admin locks voted polls, and the per-IP anonymous ballot cap holds.
# ---------------------------------------------------------------------------
class CounterIntegrityTests(TestCase):
    def setUp(self):
        self.poll = make_poll(n_choices=3)
        self.choice = self.poll.choices.first()

    def test_user_deletion_keeps_ballot_and_counters(self):
        user = User.objects.create_user("voter", password="secret")
        auth_poll = make_poll(voting_mode="authenticated", n_choices=2)
        choice = auth_poll.choices.first()
        auth_poll.cast_vote(user=user, choice_id=choice.id)
        choice.refresh_from_db()
        self.assertEqual(choice.vote_count, 1)
        # Regression: deleting the voter used to cascade the ballot away while
        # the counter kept counting — 0 ballots, 1 vote. SET_NULL keeps both.
        user.delete()
        self.assertEqual(auth_poll.ballots.count(), 1)
        self.assertIsNone(auth_poll.ballots.get().user)
        choice.refresh_from_db()
        self.assertEqual(choice.vote_count, 1)

    def test_recount_repairs_single_counter_drift(self):
        other = self.poll.choices.last()
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        self.poll.cast_vote(voter_token="tok-2", choice_id=other.id)
        self.poll.choices.update(vote_count=0, borda_score=0)  # simulate drift
        self.poll.recount()
        self.choice.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)
        self.assertEqual(other.vote_count, 1)
        self.assertEqual(self.poll.total_votes(), 2)

    def test_recount_repairs_ranked_borda(self):
        poll = make_poll(poll_type="ranked", n_choices=3)
        ids = list(poll.choices.values_list("id", flat=True))
        poll.cast_vote(voter_token="tok-1", rankings={ids[0]: 1, ids[1]: 2, ids[2]: 3})
        poll.cast_vote(voter_token="tok-2", rankings={ids[0]: 2, ids[1]: 1, ids[2]: 3})
        poll.choices.update(vote_count=0, borda_score=0)  # simulate drift
        poll.recount()
        c1, c2, c3 = (poll.choices.get(id=cid) for cid in ids)
        # Borda with N=3: rank 1 -> 3 points, rank 2 -> 2, rank 3 -> 1.
        self.assertEqual(c1.borda_score, 5)  # 3 + 2
        self.assertEqual(c2.borda_score, 5)  # 2 + 3
        self.assertEqual(c3.borda_score, 2)  # 1 + 1
        self.assertEqual(c1.vote_count, 1)
        self.assertEqual(c2.vote_count, 1)
        self.assertEqual(c3.vote_count, 0)

    def test_recount_poll_command_rebuilds_counters(self):
        from io import StringIO

        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        self.poll.choices.update(vote_count=0, borda_score=0)
        out = StringIO()
        call_command("recount_poll", stdout=out)
        self.assertIn("recounted", out.getvalue())
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)

    def test_recount_poll_command_rejects_unknown_slug(self):
        with self.assertRaises(CommandError):
            call_command("recount_poll", "no-such-slug")

    def test_case_insensitive_choice_text_rejected(self):
        # Regression: the exact-case unique constraint let "Yes" and "yes"
        # coexist as separate choices on one poll.
        self.poll.choices.create(text="Yes", order=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.poll.choices.create(text="yes", order=11)


class AdminIntegrityTests(TestCase):
    def setUp(self):
        self.poll = make_poll(n_choices=3)
        self.choice = self.poll.choices.first()
        self.rf = RequestFactory()

    def test_poll_type_readonly_once_voted(self):
        pa = PollAdmin(Poll, AdminSite())
        readonly = pa.get_readonly_fields(self.rf.get("/"), self.poll)
        self.assertNotIn("poll_type", readonly)  # still editable before votes
        self.assertIn("slug", readonly)          # existing guards preserved
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        readonly = pa.get_readonly_fields(self.rf.get("/"), self.poll)
        self.assertIn("poll_type", readonly)

    def test_choice_inline_locked_once_voted(self):
        inline = ChoiceInline(Poll, AdminSite())
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        self.assertFalse(inline.has_add_permission(self.rf.get("/"), self.poll))
        self.assertFalse(inline.has_delete_permission(self.rf.get("/"), self.poll))
        self.assertEqual(inline.get_extra(self.rf.get("/"), self.poll), 0)
        self.assertIn("text", inline.get_readonly_fields(self.rf.get("/"), self.poll))
        # A poll without ballots keeps full editing.
        fresh = make_poll(n_choices=2)
        self.assertTrue(inline.has_add_permission(self.rf.get("/"), fresh))
        self.assertEqual(inline.get_extra(self.rf.get("/"), fresh), 2)

    def test_choice_counters_readonly(self):
        ca = ChoiceAdmin(Choice, AdminSite())
        readonly = ca.get_readonly_fields(self.rf.get("/"), None)
        self.assertIn("vote_count", readonly)
        self.assertIn("borda_score", readonly)

    def test_ballot_admin_delete_recounts(self):
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        self.poll.cast_vote(voter_token="tok-2", choice_id=self.choice.id)
        ballot = Ballot.objects.get(voter_token="tok-2")
        BallotAdmin(Ballot, AdminSite()).delete_model(self.rf.post("/"), ballot)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 1)
        self.assertEqual(Ballot.objects.count(), 1)

    def test_vote_admin_delete_recounts(self):
        self.poll.cast_vote(voter_token="tok-1", choice_id=self.choice.id)
        vote = self.choice.votes.get()
        VoteAdmin(Vote, AdminSite()).delete_model(self.rf.post("/"), vote)
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.vote_count, 0)


class RateLimitTests(TestCase):
    """The per-IP successful-ballot cap (3 per rolling 24h, anonymous polls)."""

    def setUp(self):
        self.poll = make_poll(n_choices=2)
        self.choice = self.poll.choices.first()

    def test_fourth_anonymous_ballot_from_same_ip_rejected(self):
        for i in range(3):
            self.poll.cast_vote(
                voter_token=f"tok-{i}", choice_id=self.choice.id, client_ip="9.9.9.9"
            )
        with self.assertRaises(RateLimited):
            self.poll.cast_vote(
                voter_token="tok-3", choice_id=self.choice.id, client_ip="9.9.9.9"
            )
        # A distinct IP is unaffected.
        self.poll.cast_vote(
            voter_token="tok-4", choice_id=self.choice.id, client_ip="8.8.8.8"
        )
        self.assertEqual(Ballot.objects.filter(poll=self.poll).count(), 4)

    def test_ballots_older_than_24h_do_not_count(self):
        self.poll.cast_vote(
            voter_token="tok-old", choice_id=self.choice.id, client_ip="9.9.9.9"
        )
        Ballot.objects.update(created_at=timezone.now() - timedelta(hours=25))
        self.poll.cast_vote(
            voter_token="tok-new", choice_id=self.choice.id, client_ip="9.9.9.9"
        )
        self.assertEqual(Ballot.objects.filter(poll=self.poll).count(), 2)

    def test_authenticated_polls_are_not_ip_capped(self):
        poll = make_poll(voting_mode="authenticated", n_choices=2)
        choice = poll.choices.first()
        for i in range(4):
            user = User.objects.create_user(f"u{i}", password="x")
            poll.cast_vote(user=user, choice_id=choice.id, client_ip="9.9.9.9")
        self.assertEqual(poll.ballots.count(), 4)

    def test_vote_view_returns_rate_limit_error_after_cap(self):
        for _ in range(3):
            self.client.post(
                f"/{self.poll.slug}/vote/",
                {"choice": self.choice.id},
                REMOTE_ADDR="9.9.9.9",
            )
            self.client.cookies.clear()  # cookie-less: each POST mints a fresh token
        resp = self.client.post(
            f"/{self.poll.slug}/vote/",
            {"choice": self.choice.id},
            REMOTE_ADDR="9.9.9.9",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Too many votes from this network")
        self.assertEqual(Ballot.objects.filter(poll=self.poll).count(), 3)
