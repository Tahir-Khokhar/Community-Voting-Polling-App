"""
Custom template tags for the polls app.

  * ``{% percentage_bar choice poll total %}`` — renders a Tailwind-styled
    result bar with the right metric (direct votes for single polls, Borda
    score for ranked polls) and the percentage filled in. ``total`` is the
    poll's total metric, computed once by the caller and passed in so the tag
    does not re-run an aggregate query per choice (which would be an N+1 when
    the results partial loops over every choice).
  * ``{% message_alert message %}`` — renders a Django messages-framework
    alert (severity class + matching icon + text) from a single message. The
    severity is decided once here instead of duplicated as if/elif chains in
    the template.
  * ``{% has_voted poll user voter_token %}`` — boolean check from a template.
  * ``{% pct value total %}`` — integer percentage, safe against zero total.
"""

from django import template

register = template.Library()


@register.simple_tag
def pct(value, total):
    """Return value as an integer percentage of total (0 when total is 0)."""
    if not total:
        return 0
    return round(int(value) / int(total) * 100)


@register.inclusion_tag("polls/partials/_bar.html")
def percentage_bar(choice, poll, total):
    """Render a result bar for ``choice`` within ``poll``.

    ``total`` is the poll's total metric (sum of votes or Borda scores),
    computed once by the caller and passed in so we do not re-run an aggregate
    query per choice. The score is read directly off the choice fields rather
    than via ``choice.effective_score``: that property dereferences
    ``choice.poll``, which is an N+1 query when the choices queryset was not
    built with ``select_related('poll')``. Reading the field + the passed-in
    ``poll`` avoids that lookup entirely.
    """
    score = choice.borda_score if poll.is_ranked else choice.vote_count
    percent = (score / total * 100) if total else 0
    return {
        "choice": choice,
        "poll": poll,
        "score": score,
        "total": total,
        "percent": round(percent, 1),
        "metric_label": "Borda" if poll.is_ranked else "votes",
    }


# --- Django messages-framework alert rendering ----------------------------
# Severity is decided once here (highest severity wins) so the template does
# not duplicate a four-way if/elif chain for the CSS classes AND the icon.
# Keys mirror Django's built-in message levels/tags.
_ALERT_CSS = {
    "error": "border-red-200 bg-red-50 text-red-700",
    "warning": "border-amber-200 bg-amber-50 text-amber-700",
    "success": "border-emerald-200 bg-emerald-50 text-emerald-700",
    "info": "border-brand-200 bg-brand-50 text-brand-700",
}
_ALERT_ICON = {
    "error": ('<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" '
              'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round"><path d="M12 3l9 17H3z"/><path d="M12 9v4"/>'
              '<circle cx="12" cy="16.5" r="1" fill="currentColor" stroke="none"/></svg>'),
    "warning": ('<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                'stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/>'
                '<path d="M12 7v5"/><circle cx="12" cy="16" r="1" fill="currentColor" '
                'stroke="none"/></svg>'),
    "success": ('<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>'),
    "info": ('<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/>'
             '<circle cx="12" cy="7.5" r="1" fill="currentColor" stroke="none"/>'
             '<path d="M12 10v5"/></svg>'),
}
# Order matters: highest severity first so a multi-tag message (e.g. a custom
# "warning" + "error") reports as error.
_ALERT_PRIORITY = ("error", "warning", "success")


@register.inclusion_tag("polls/partials/_message_alert.html")
def message_alert(message):
    """Render a Django messages-framework alert for a single ``message``.

    Decides the severity class and matching icon once (highest severity wins,
    falling back to ``info``) so the template never duplicates the branch.
    The message text is rendered through the partial with default autoescaping.
    """
    tags = (message.tags or "").lower()
    severity = "info"
    for key in _ALERT_PRIORITY:
        if key in tags:
            severity = key
            break
    return {
        "level_css": _ALERT_CSS[severity],
        "icon_html": _ALERT_ICON[severity],
        "message": message,
    }


@register.simple_tag
def has_voted(poll, user, voter_token):
    """Has the given user/token already voted on ``poll``?"""
    return poll.has_voted(user, voter_token)
