"""Admin registration for the polls app."""

from django.contrib import admin

from .models import Ballot, Choice, Poll, Vote


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 2
    ordering = ("order",)


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "poll_type", "voting_mode", "total_ballots", "is_expired", "results_frozen")
    list_filter = ("poll_type", "voting_mode", "results_frozen")
    search_fields = ("title", "slug", "description")
    readonly_fields = ("slug", "created_at")
    inlines = [ChoiceInline]


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ("text", "poll", "order", "vote_count", "borda_score")
    list_filter = ("poll__poll_type",)
    search_fields = ("text",)
    autocomplete_fields = ("poll",)


@admin.register(Ballot)
class BallotAdmin(admin.ModelAdmin):
    list_display = ("poll", "user", "voter_token", "created_at")
    list_filter = ("poll",)
    search_fields = ("voter_token", "user__username")
    readonly_fields = ("created_at",)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("ballot", "choice", "rank")
    list_filter = ("choice__poll",)
