"""
Models for the Community Voting & Polling App.

Design notes
------------
A *Poll* has many *Choices*. A *Ballot* represents one voter's submission on
a poll (either an authenticated user or an anonymous token). A *Vote* is one
ranked row inside a ballot — for single-choice polls there is exactly one
Vote per ballot; for ranked polls there is one Vote per choice with a rank.

Denormalised counters (``Choice.vote_count`` and ``Choice.borda_score``) are
updated inside the same transaction that inserts the ballot, guarded by
``select_for_update()`` on the affected ``Choice`` rows. On SQLite this is a
no-op (the database-level write lock already serialises writers), but the
code is portable and correct on PostgreSQL / MySQL where row-level locking
actually fires.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.db.models import CheckConstraint, Count, Q, Sum, UniqueConstraint
from django.db.models.functions import Lower
from django.utils import timezone

from autoslug import AutoSlugField


class Poll(models.Model):
    """A single poll question with a set of choices."""

    class PollType(models.TextChoices):
        SINGLE = "single", "Single choice"
        RANKED = "ranked", "Ranked choice"

    class VotingMode(models.TextChoices):
        ANONYMOUS = "anonymous", "Anonymous"
        AUTHENTICATED = "authenticated", "Authenticated"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    slug = AutoSlugField(
        populate_from="title",
        unique=True,
        always_update=False,
        help_text="Auto-generated unique URL slug.",
    )
    poll_type = models.CharField(
        max_length=10, choices=PollType.choices, default=PollType.SINGLE
    )
    voting_mode = models.CharField(
        max_length=13, choices=VotingMode.choices, default=VotingMode.ANONYMOUS
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="polls",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="When the poll closes. Blank = never."
    )
    results_frozen = models.BooleanField(
        default=False,
        help_text="When True, results are hidden until unfrozen (manual freeze).",
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            # slug is already covered by AutoSlugField(unique=True), so we do
            # not add a redundant index there. expires_at is used to filter
            # active/expired polls, so it benefits from an index.
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    # --- Status helpers ---------------------------------------------------
    @property
    def is_expired(self) -> bool:
        """True if the poll's expiry has passed."""
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        """A poll is active when it has not expired."""
        return not self.is_expired

    @property
    def is_ranked(self) -> bool:
        return self.poll_type == self.PollType.RANKED

    @property
    def requires_auth(self) -> bool:
        return self.voting_mode == self.VotingMode.AUTHENTICATED

    def results_visible(self, user) -> bool:
        """Results are visible when not frozen, or when the viewer is the owner."""
        if not self.results_frozen:
            return True
        return user is not None and (user.is_superuser or user == self.created_by)

    def has_voted(self, user, voter_token) -> bool:
        """Has this user/token already cast a ballot on this poll?"""
        if user is not None and user.is_authenticated:
            return self.ballots.filter(user=user).exists()
        if voter_token:
            return self.ballots.filter(voter_token=voter_token).exists()
        return False

    # --- Aggregate counts -------------------------------------------------
    def total_ballots(self) -> int:
        return self.ballots.count()

    def total_votes(self) -> int:
        """Sum of every choice's primary metric (votes for single, Borda for ranked).

        Uses an aggregate query rather than iterating in Python, so this stays
        cheap even when the ``percentage_bar`` template tag calls it per choice.
        """
        metric = "borda_score" if self.is_ranked else "vote_count"
        return self.choices.aggregate(total=Sum(metric))["total"] or 0

    def recount(self):
        """
        Recalculate the denormalised ``vote_count`` / ``borda_score`` counters
        from the stored ``Vote`` rows, repairing any drift (e.g. after a ballot
        or vote row was deleted out-of-band rather than through ``cast_vote``).

        Single polls: one Vote row per ballot, so ``vote_count`` is the number
        of Vote rows and ``borda_score`` is zeroed. Ranked polls: ``vote_count``
        counts first-place votes and ``borda_score`` is the sum of
        ``N - rank + 1`` points (N = the poll's *current* choice count —
        historic ballots are re-scored against today's N, which is the closest
        possible repair when choices were added after voting).
        """
        stats = {
            row["choice_id"]: row
            for row in Vote.objects.filter(choice__poll=self)
            .values("choice_id")
            .annotate(
                n_votes=Count("id"),
                first_place=Count("id", filter=Q(rank=1)),
                rank_sum=Sum("rank"),
            )
        }
        n = self.choices.count()  # current N for Borda point scaling
        for choice in self.choices.all():
            row = stats.get(choice.id)
            if self.is_ranked:
                choice.vote_count = row["first_place"] if row else 0
                choice.borda_score = (
                    row["n_votes"] * (n + 1) - row["rank_sum"] if row else 0
                )
            else:
                choice.vote_count = row["n_votes"] if row else 0
                choice.borda_score = 0
            choice.save(update_fields=["vote_count", "borda_score"])

    # --- Vote casting -----------------------------------------------------
    def cast_vote(self, *, user=None, voter_token=None, choice_id=None, rankings=None, client_ip=None):
        """
        Atomically record a ballot and update denormalised counters.

        For single-choice polls pass ``choice_id``.
        For ranked polls pass ``rankings`` — a dict mapping choice_id -> rank
        (1 = favourite). Every choice must be ranked exactly once.
        ``client_ip`` (optional, anonymous polls only — the view passes it for
        anonymous polls) enables the per-IP successful-ballot cap.

        Returns the created ``Ballot``. Raises ``PollClosed`` if the poll has
        expired, ``AlreadyVoted`` if a ballot already exists, ``InvalidVote``
        for malformed input, and ``RateLimited`` when the per-IP cap is hit.
        """
        from .exceptions import AlreadyVoted, InvalidVote, PollClosed, RateLimited

        # --- Input validation (cheap reads; no state guarantees needed yet) ---
        # Shape-check the submitted vote before acquiring any locks, so a
        # malformed request never contends with real voters for the poll lock.
        if self.is_ranked:
            rankings = rankings or {}
            choice_ids = set(self.choices.values_list("id", flat=True))
            if set(rankings.keys()) != choice_ids:
                raise InvalidVote("You must rank every choice exactly once.")
            ranks_given = list(rankings.values())
            expected = list(range(1, len(choice_ids) + 1))
            if sorted(ranks_given) != expected:
                raise InvalidVote("Ranks must be 1..N with no gaps or duplicates.")
        else:
            if choice_id is None:
                raise InvalidVote("A choice is required.")
            if not self.choices.filter(id=choice_id).exists():
                raise InvalidVote("Invalid choice.")
            rankings = {int(choice_id): 1}

        # --- Transaction: lock the poll, re-check state, then write ---
        # Locking the poll row serialises this vote against any concurrent
        # state change (an expiry edit or a freeze toggle) so the state checks
        # below are consistent with the writes that follow. On SQLite
        # select_for_update() is a no-op (the DB-level write lock already
        # serialises writers); on PostgreSQL/MySQL it takes a real row lock.
        with transaction.atomic():
            poll = Poll.objects.select_for_update().get(pk=self.pk)

            if poll.is_expired:
                raise PollClosed("This poll has closed.")
            if poll.requires_auth and (user is None or not user.is_authenticated):
                raise InvalidVote("You must log in to vote on this poll.")
            if not poll.requires_auth and not voter_token:
                raise InvalidVote("Missing anonymous voter token.")

            # Lock the choice rows we are about to mutate.
            choices_qs = self.choices.select_for_update().filter(id__in=rankings.keys())
            choices_by_id = {c.id: c for c in choices_qs}

            if poll.has_voted(user, voter_token):
                raise AlreadyVoted("You have already voted on this poll.")

            # Per-IP successful-ballot cap (anonymous polls). The attempt
            # throttle slows scripted spam; this caps how many ballots one IP
            # may actually record on one poll per rolling 24h window, closing
            # the cookie-less bypass (a fresh token per request). An abuse
            # brake, not a security boundary — best-effort under concurrency.
            if client_ip and not poll.requires_auth:
                limit = settings.POLL_SETTINGS["ANON_IP_BALLOT_LIMIT_PER_DAY"]
                window_start = timezone.now() - timedelta(days=1)
                recent = poll.ballots.filter(
                    client_ip=client_ip, created_at__gte=window_start
                ).count()
                if recent >= limit:
                    raise RateLimited(
                        "Too many votes from this network on this poll. "
                        "Please try again later."
                    )

            # The has_voted() check above and this insert are now both inside
            # the poll-locked transaction, so the normal flow is race-free.
            # The unique_ballot_per_user / unique_ballot_per_token constraint
            # is still the hard database-level guard: if two first-votes on the
            # same token/user ever both reach the insert (e.g. via separate
            # connections that did not share the poll lock), the second trips
            # the constraint and we translate IntegrityError into AlreadyVoted
            # rather than surfacing a 500.
            try:
                with transaction.atomic():
                    ballot = Ballot.objects.create(
                        poll=self,
                        user=user if (user is not None and user.is_authenticated) else None,
                        # CharField is NOT NULL — use "" not None for authenticated polls.
                        voter_token=voter_token if (voter_token and not poll.requires_auth) else "",
                        client_ip=client_ip or None,
                    )
            except IntegrityError as exc:
                raise AlreadyVoted("You have already voted on this poll.") from exc

            for choice_id, rank in rankings.items():
                choice = choices_by_id[choice_id]
                if poll.is_ranked:
                    # Borda: rank 1 -> N points, rank N -> 1 point.
                    n = len(choices_by_id)
                    points = max(1, n - rank + 1)
                    choice.borda_score += points
                    if rank == 1:
                        choice.vote_count += 1
                else:
                    choice.vote_count += 1
                choice.save(update_fields=["vote_count", "borda_score"])

            vote_rows = [
                Vote(ballot=ballot, choice=choices_by_id[cid], rank=r if poll.is_ranked else None)
                for cid, r in rankings.items()
            ]
            Vote.objects.bulk_create(vote_rows)

        return ballot


class Choice(models.Model):
    """One option on a poll."""

    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    vote_count = models.PositiveIntegerField(
        default=0, help_text="Direct votes (single) or first-place votes (ranked)."
    )
    borda_score = models.PositiveIntegerField(
        default=0, help_text="Borda points for ranked polls."
    )

    class Meta:
        ordering = ("order", "id")
        constraints = [
            # Case-insensitive uniqueness of choice text within a poll, so
            # "Yes" and "yes" cannot both be created (the previous exact-case
            # constraint treated them as distinct options).
            UniqueConstraint(Lower("text"), "poll", name="unique_choice_text_per_poll_ci"),
        ]

    def __str__(self) -> str:
        return self.text

    @property
    def effective_score(self) -> int:
        """The number the percentage bar is built from."""
        return self.borda_score if self.poll.is_ranked else self.vote_count


class Ballot(models.Model):
    """One voter's submission on a poll."""

    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="ballots")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        # SET_NULL (not CASCADE): deleting a user must not cascade their
        # ballots away — the stored counters count those ballots' votes, so a
        # cascade would leave vote_count/borda_score counting nothing.
        on_delete=models.SET_NULL,
        related_name="ballots",
    )
    voter_token = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Signed anonymous voter identifier (see polls.signing).",
    )
    client_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Client IP for anonymous ballots (per-IP ballot cap; see cast_vote).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            # One ballot per authenticated user per poll.
            UniqueConstraint(
                fields=["poll", "user"],
                condition=Q(user__isnull=False),
                name="unique_ballot_per_user",
            ),
            # One ballot per anonymous token per poll.
            UniqueConstraint(
                fields=["poll", "voter_token"],
                condition=~Q(voter_token=""),
                name="unique_ballot_per_token",
            ),
        ]

    def __str__(self) -> str:
        who = self.user.get_username() if self.user else f"anon:{self.voter_token[:8]}"
        return f"Ballot by {who} on {self.poll.title}"


class Vote(models.Model):
    """A single ranked row inside a ballot (one per choice)."""

    ballot = models.ForeignKey(Ballot, on_delete=models.CASCADE, related_name="votes")
    choice = models.ForeignKey(Choice, on_delete=models.CASCADE, related_name="votes")
    rank = models.PositiveIntegerField(
        null=True, blank=True, help_text="1-based rank for ranked polls; NULL for single."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("rank",)
        constraints = [
            UniqueConstraint(fields=["ballot", "choice"], name="unique_vote_per_ballot_choice"),
            # Rank is NULL for single-choice ballots, otherwise a 1-based
            # positive integer. Enforced at the database level as well as in
            # cast_vote() / RankedVoteForm, so a buggy write path can never
            # store a zero or negative rank.
            CheckConstraint(
                condition=Q(rank__isnull=True) | Q(rank__gte=1),
                name="vote_rank_null_or_positive",
            ),
        ]

    def __str__(self) -> str:
        suffix = f" #{self.rank}" if self.rank else ""
        return f"Vote{suffix} for {self.choice.text}"
