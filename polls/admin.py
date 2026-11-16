"""Admin registration for the polls app."""

from django.contrib import admin

from .models import Ballot, Choice, Poll, Vote


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 2
    ordering = ("order",)

    def _locked(self, obj):
        """A poll that already has ballots must not gain, lose, or re-label
        choices — recorded ballots (and their Borda scores) refer to the
        choice set that existed when the votes were cast."""
        return obj is not None and obj.total_ballots() > 0

    def has_add_permission(self, request, obj):
        return not self._locked(obj)

    def has_delete_permission(self, request, obj):
        return not self._locked(obj)

    def get_extra(self, request, obj=None, **kwargs):
        # No blank "add another choice" rows once the poll has ballots.
        return 0 if self._locked(obj) else self.extra

    def get_readonly_fields(self, request, obj=None):
        if self._locked(obj):
            return ("text",)
        return super().get_readonly_fields(request, obj)


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "poll_type", "voting_mode", "total_ballots", "is_expired", "results_frozen")
    list_filter = ("poll_type", "voting_mode", "results_frozen")
    search_fields = ("title", "slug", "description")
    readonly_fields = ("slug", "created_at")
    inlines = [ChoiceInline]

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if obj is not None and obj.total_ballots() > 0:
            # The scoring model is baked into recorded ballots — switching a
            # voted poll between single and ranked would corrupt the results.
            return readonly + ("poll_type",)
        return readonly


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ("text", "poll", "order", "vote_count", "borda_score")
    list_filter = ("poll__poll_type",)
    search_fields = ("text",)
    autocomplete_fields = ("poll",)
    # The counters are denormalised cache values maintained by cast_vote() /
    # recount(); typing them by hand desyncs them from the Ballot/Vote rows.
    readonly_fields = ("vote_count", "borda_score")


@admin.register(Ballot)
class BallotAdmin(admin.ModelAdmin):
    list_display = ("poll", "user", "voter_token", "client_ip", "created_at")
    list_filter = ("poll",)
    search_fields = ("voter_token", "user__username")
    # Ballots are immutable operational records: editing one by hand (its poll,
    # user, or token) would desync the denormalised counters from the rows.
    readonly_fields = ("poll", "user", "voter_token", "client_ip", "created_at")

    def delete_model(self, request, obj):
        poll = obj.poll
        super().delete_model(request, obj)
        poll.recount()  # deleting a ballot removes its votes — recompute counters

    def delete_queryset(self, request, queryset):
        poll_ids = set(queryset.values_list("poll_id", flat=True))
        super().delete_queryset(request, queryset)
        for poll in Poll.objects.filter(id__in=poll_ids):
            poll.recount()


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("ballot", "choice", "rank")
    list_filter = ("choice__poll",)
    # Same immutability rule as Ballot: hand-editing vote rows (or deleting
    # them) would leave the stored counters counting votes that no longer exist.
    readonly_fields = ("ballot", "choice", "rank")

    def delete_model(self, request, obj):
        poll = obj.choice.poll
        super().delete_model(request, obj)
        poll.recount()

    def delete_queryset(self, request, queryset):
        poll_ids = set(queryset.values_list("choice__poll_id", flat=True))
        super().delete_queryset(request, queryset)
        for poll in Poll.objects.filter(id__in=poll_ids):
            poll.recount()
