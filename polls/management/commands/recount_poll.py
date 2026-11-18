"""
Rebuild the denormalised vote counters from the stored Vote rows.

Usage:
    python manage.py recount_poll              # recount EVERY poll
    python manage.py recount_poll <slug> ...   # recount only the given polls

Repairs any drift between ``Choice.vote_count`` / ``Choice.borda_score`` and
the actual ``Vote`` rows (e.g. after a ballot or vote row was deleted
out-of-band, or after a crash between the ballot insert and the counter
update). The write goes through ``Poll.recount()``, the same repair path the
admin uses after deleting ballots/votes, so single and Borda-scored ranked
polls are both handled.

Exits with ``CommandError`` if a named slug does not exist, so a typo on the
command line fails loudly instead of silently recounting nothing.
"""

from django.core.management.base import BaseCommand, CommandError

from polls.models import Poll


class Command(BaseCommand):
    help = (
        "Rebuild Choice.vote_count / Choice.borda_score from the stored Vote "
        "rows. With no arguments every poll is recounted; pass slugs to "
        "recount specific polls."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "slugs",
            nargs="*",
            help="Optional poll slugs. Omit to recount every poll.",
        )

    def handle(self, *args, **options):
        slugs = options["slugs"]
        if slugs:
            # Validate every slug up front so a single typo aborts the whole
            # run before any counter is touched.
            polls = list(Poll.objects.filter(slug__in=slugs))
            found = {poll.slug for poll in polls}
            missing = [slug for slug in slugs if slug not in found]
            if missing:
                raise CommandError(
                    "Unknown poll slug(s): %s" % ", ".join(sorted(set(missing)))
                )
        else:
            polls = list(Poll.objects.all())

        recounted = 0
        for poll in polls:
            ballots = poll.total_ballots()
            poll.recount()
            recounted += 1
            self.stdout.write(
                "%s: recounted (%d ballot%s, %d choice%s, %s)"
                % (
                    poll.slug,
                    ballots,
                    "" if ballots == 1 else "s",
                    poll.choices.count(),
                    "" if poll.choices.count() == 1 else "s",
                    "ranked/Borda" if poll.is_ranked else "single-choice",
                )
            )

        self.stdout.write(self.style.SUCCESS("Done: %d poll(s) recounted." % recounted))
