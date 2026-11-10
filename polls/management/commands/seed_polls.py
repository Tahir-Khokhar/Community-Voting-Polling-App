"""
Seed the database with sample polls so the app is testable on first run.

Usage:
    python manage.py seed_polls

Creates a demo user, 5 polls (a mix of single/ranked × anonymous/authenticated,
one with an expiry, one frozen), and a handful of votes so the result bars
aren't empty on first load. Idempotent: re-running skips polls whose slug
already exists.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from polls.models import Poll
from polls.signing import mint_voter_token, verify_voter_token

User = get_user_model()


SAMPLE = [
    {
        "title": "Which feature should we build next?",
        "description": "Vote on the team's next sprint priority.",
        "poll_type": Poll.PollType.SINGLE,
        "voting_mode": Poll.VotingMode.ANONYMOUS,
        "expires_at": timezone.now() + timedelta(days=7),
        "choices": ["Dark mode", "Export to CSV", "Public API", "Mobile app"],
        "votes": [12, 5, 8, 3],
    },
    {
        "title": "Rank our next team social event",
        "description": "Drag-and-drop is not supported — pick a rank for each option.",
        "poll_type": Poll.PollType.RANKED,
        "voting_mode": Poll.VotingMode.ANONYMOUS,
        "expires_at": None,
        "choices": ["Escape room", "Bowling", "Board game night", "Dinner out", "Hike"],
        "ranked_ballots": [
            [1, 3, 2, 4, 5],
            [1, 2, 3, 4, 5],
            [2, 1, 3, 5, 4],
            [1, 4, 2, 3, 5],
            [3, 2, 1, 5, 4],
        ],
    },
    {
        "title": "Best code editor for the team?",
        "description": "Authenticated poll — only signed-in members can vote.",
        "poll_type": Poll.PollType.SINGLE,
        "voting_mode": Poll.VotingMode.AUTHENTICATED,
        "expires_at": None,
        "choices": ["VS Code", "Neovim", "JetBrains", "Zed"],
        "votes": [9, 4, 6, 2],
    },
    {
        "title": "Lunch pick for Friday (closed example)",
        "description": "This poll has already expired — voting is closed.",
        "poll_type": Poll.PollType.SINGLE,
        "voting_mode": Poll.VotingMode.ANONYMOUS,
        "expires_at": timezone.now() - timedelta(days=1),
        "choices": ["Sushi", "Tacos", "Curry", "Salad bar"],
        "votes": [7, 11, 6, 2],
    },
    {
        "title": "Conference talk topics — results hidden",
        "description": "An owner-frozen poll: results are hidden from voters.",
        "poll_type": Poll.PollType.SINGLE,
        "voting_mode": Poll.VotingMode.ANONYMOUS,
        "expires_at": None,
        "results_frozen": True,
        "choices": ["Web performance", "Django internals", "HTMX patterns", "Security"],
        "votes": [3, 5, 2, 1],
    },
]


class Command(BaseCommand):
    help = "Seed sample polls, choices and votes for demo/testing."

    def handle(self, *args, **options):
        owner, created = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.com", "is_staff": True, "is_superuser": True},
        )
        if created:
            owner.set_password("demo1234")
            owner.save()
            self.stdout.write(self.style.SUCCESS("Created demo user: demo / demo1234"))

        created_count = 0
        skipped_count = 0
        for entry in SAMPLE:
            if Poll.objects.filter(title=entry["title"]).exists():
                skipped_count += 1
                continue

            poll = Poll.objects.create(
                title=entry["title"],
                description=entry["description"],
                poll_type=entry["poll_type"],
                voting_mode=entry["voting_mode"],
                expires_at=entry.get("expires_at"),
                results_frozen=entry.get("results_frozen", False),
                created_by=owner,
            )
            for idx, text in enumerate(entry["choices"]):
                poll.choices.create(text=text, order=idx)

            # Cast the sample votes. Anonymous polls use signed tokens;
            # authenticated polls use one-off voter accounts (the unique
            # constraint is per-user, so each ballot needs a distinct user).
            choices = list(poll.choices.all())

            # For an expired poll we can't call cast_vote directly (it raises
            # PollClosed), so we temporarily reopen it, cast the historical
            # ballots, then restore the original expiry.
            original_expiry = poll.expires_at
            if poll.is_expired:
                poll.expires_at = timezone.now() + timedelta(days=7)
                poll.save(update_fields=["expires_at"])

            try:
                if poll.voting_mode == Poll.VotingMode.ANONYMOUS:
                    if poll.poll_type == Poll.PollType.SINGLE:
                        for choice, count in zip(choices, entry["votes"]):
                            for _ in range(count):
                                token = mint_voter_token(poll.id)
                                voter_id = verify_voter_token(token, poll.id)
                                poll.cast_vote(voter_token=voter_id, choice_id=choice.id)
                    else:
                        # ranked_ballots: list of rank-per-choice lists (order
                        # matches the choices list above).
                        for ranks in entry["ranked_ballots"]:
                            token = mint_voter_token(poll.id)
                            voter_id = verify_voter_token(token, poll.id)
                            rankings = {
                                choices[i].id: ranks[i] for i in range(len(choices))
                            }
                            poll.cast_vote(voter_token=voter_id, rankings=rankings)
                else:
                    # Authenticated: each ballot needs its own user.
                    for idx, count in enumerate(entry["votes"]):
                        for k in range(count):
                            u, _ = User.objects.get_or_create(
                                username=f"voter_{poll.id}_{idx}_{k}",
                                defaults={"email": f"v{poll.id}_{idx}_{k}@example.com"},
                            )
                            poll.cast_vote(user=u, choice_id=choices[idx].id)
            finally:
                if original_expiry != poll.expires_at:
                    poll.expires_at = original_expiry
                    poll.save(update_fields=["expires_at"])

            created_count += 1
            self.stdout.write(f"  + {poll.title}  ({poll.slug})")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created_count} poll(s), skipped {skipped_count} existing."
        ))
