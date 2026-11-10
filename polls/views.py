"""
Class-based views for the polls app.

URL names (see polls/urls.py):
  polls:home          /                       HomeView            (ListView)
  polls:create        /create/                PollCreateView      (CreateView)
  polls:detail        /<slug:slug>/           PollDetailView      (DetailView)
  polls:vote          /<slug:slug>/vote/      VoteView            (View, POST)
  polls:results       /<slug:slug>/results/   ResultsPartialView  (View, HTMX partial)
  polls:results_page  /<slug:slug>/results-page/  PollResultsView (DetailView)
  polls:widget        /<slug:slug>/widget/    WidgetView          (DetailView, iframe-safe)
  polls:share         /<slug:slug>/share/     ShareView           (DetailView)
  polls:qr            /<slug:slug>/qr.png     QRCodeView          (View, image/png)
  polls:freeze        /<slug:slug>/freeze/    FreezeToggleView   (View, owner only)

The HTMX flow
-------------
The detail page renders a container ``#poll-interactive`` holding EITHER the
vote form partial OR the results partial, depending on whether the viewer has
voted / the poll is closed.

  * Submitting the vote form does an ``hx-post`` to ``polls:vote`` and swaps
    in the results partial.
  * The results partial's wrapper carries ``hx-trigger="every 3s"`` pointing
    at ``polls:results`` so the bars live-update without a full page reload.
"""

from __future__ import annotations

import io

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from .exceptions import AlreadyVoted, InvalidVote, PollClosed
from .forms import ChoiceFormSet, PollCreateForm, SignUpForm, build_vote_form
from .models import Poll
from .signing import cookie_name, mint_voter_token, verify_voter_token
from .throttling import vote_attempt_allowed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_anon_token(request, poll) -> str | None:
    """
    For anonymous polls, return the *voter id* to use as the ballot uniqueness
    key — deriving it from the signed cookie token, or minting a fresh one
    (and stashing the signed token on the request so the response hook can set
    the cookie). Returns None for authenticated polls.

    Note: the *signed token* (the full signed blob) goes in the cookie; the
    *voter id* (the 16-char random hex inside it) is what we store on
    ``Ballot.voter_token``. This keeps the column short (well under its
    max_length) and decouples uniqueness from SECRET_KEY rotation. Storing the
    full signed blob instead would exceed ``Ballot.voter_token``'s max_length
    and crash on databases that enforce it (e.g. PostgreSQL).
    """
    if poll.requires_auth:
        return None
    name = cookie_name(poll.id)
    raw = request.COOKIES.get(name)
    if raw:
        voter_id = verify_voter_token(raw, poll.id)
        if voter_id:
            return voter_id
    # Mint a new signed token for the cookie, then extract its voter id.
    token = mint_voter_token(poll.id)
    request._anon_token_to_set = token
    return verify_voter_token(token, poll.id)


class VoterTokenCookieMixin:
    """Set the anonymous voter cookie on the response when one was minted."""

    def _attach_token_cookie(self, response, poll):
        token = getattr(self.request, "_anon_token_to_set", None)
        if token is None or poll.requires_auth:
            return response
        # Cookie lifetime is capped at the signed token's max age (see
        # ANON_COOKIE_MAX_AGE in settings) so the cookie can never outlive the
        # token inside it — otherwise an expired token + live cookie would let
        # a visitor be minted a fresh token and vote again.
        # Secure=True in production (DEBUG off, HTTPS) so the cookie is never
        # leaked over plain HTTP; in dev over HTTP it must stay False or the
        # browser refuses to set it.
        response.set_cookie(
            cookie_name(poll.id),
            token,
            httponly=True,
            samesite="Lax",
            max_age=settings.POLL_SETTINGS["ANON_COOKIE_MAX_AGE"],
            secure=not settings.DEBUG,
        )
        return response


# ---------------------------------------------------------------------------
# Listing & creation
# ---------------------------------------------------------------------------

class HomeView(ListView):
    """Landing page: active and recently created polls."""

    template_name = "polls/home.html"
    context_object_name = "polls"
    paginate_by = 12

    def get_queryset(self):
        # Annotate choice/ballot counts up front so the listing template does
        # not fire a COUNT query per poll (an N+1 across the whole page).
        # distinct=True avoids the join-fan-out that double-Counts otherwise
        # produce when two different FK relations are annotated together.
        return (
            Poll.objects.all()
            .select_related("created_by")
            .annotate(
                ballot_count=Count("ballots", distinct=True),
                choice_count=Count("choices", distinct=True),
            )
            .order_by("-created_at")
        )


class PollCreateView(LoginRequiredMixin, CreateView):
    """Create a new poll together with its choices (inline formset)."""

    model = Poll
    form_class = PollCreateForm
    template_name = "polls/poll_create.html"
    success_url = reverse_lazy("polls:home")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            ctx["choice_formset"] = ChoiceFormSet(self.request.POST, instance=self.object)
        else:
            ctx["choice_formset"] = ChoiceFormSet(instance=self.object)
        return ctx

    def form_valid(self, form):
        """
        Validate the choices formset against the *unsaved* poll, and only
        persist anything once both the form and the formset are valid. The
        poll is saved first (so it gets a pk + slug), then each choice is
        re-pointed at the saved poll before being written.
        """
        self.object = form.save(commit=False)
        self.object.created_by = self.request.user

        formset = ChoiceFormSet(self.request.POST, instance=self.object)
        if not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, choice_formset=formset)
            )

        self.object.save()  # now has a pk + slug
        formset.instance = self.object
        for idx, choice in enumerate(formset.save(commit=False)):
            choice.poll = self.object  # FK was None at construction time
            choice.order = idx
            choice.save()
        messages.success(self.request, "Poll created.")
        # Skip ModelFormMixin.form_valid() — it would call form.save() again
        # (a redundant UPDATE) on the instance we already persisted above.
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        formset = ChoiceFormSet(self.request.POST)
        return self.render_to_response(
            self.get_context_data(form=form, choice_formset=formset)
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class SignUpView(CreateView):
    """
    User registration. On success the new account is signed in immediately
    (no separate "now log in" step) and greeted on the home page.
    """

    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("polls:home")

    def dispatch(self, request, *args, **kwargs):
        # A signed-in visitor has no reason to see the signup form.
        if request.user.is_authenticated:
            return redirect("polls:home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(
            self.request,
            f"Welcome, {self.object.username}! Your account is ready.",
        )
        return response


# ---------------------------------------------------------------------------
# Detail & voting
# ---------------------------------------------------------------------------

class PollDetailView(VoterTokenCookieMixin, DetailView):
    """Show a poll. Renders either the vote form or the results partial."""

    model = Poll
    template_name = "polls/poll_detail.html"
    context_object_name = "poll"

    def get_object(self, queryset=None):
        return get_object_or_404(Poll, slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        poll = self.object
        voter_token = _ensure_anon_token(self.request, poll)
        ctx["voter_token"] = voter_token
        ctx["has_voted"] = poll.has_voted(self.request.user, voter_token)
        ctx["results_visible"] = poll.results_visible(self.request.user)
        ctx["show_results"] = ctx["has_voted"] or poll.is_expired
        if not ctx["show_results"]:
            if poll.requires_auth and not self.request.user.is_authenticated:
                ctx["needs_login"] = True
            else:
                ctx["vote_form"] = build_vote_form(poll)
        return ctx

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        self._attach_token_cookie(response, self.object)
        return response


class VoteView(VoterTokenCookieMixin, View):
    """Handle a vote submission (HTMX or regular POST). Returns results partial."""

    template_partial = "polls/partials/_results.html"
    form_partial = "polls/partials/_vote_form.html"

    def get_object(self):
        return get_object_or_404(Poll, slug=self.kwargs["slug"])

    def post(self, request, slug):
        poll = self.get_object()
        # Abuse brake: limit vote attempts per IP per poll (see throttling.py).
        # The real one-vote-per-token guarantee is the signed token + DB
        # constraint; this only slows scripted spam of the vote endpoint.
        if not vote_attempt_allowed(request, poll.id):
            context = {
                "poll": poll,
                "voter_token": _ensure_anon_token(request, poll),
                "results_visible": poll.results_visible(request.user),
                "show_results": True,
                "error": "Too many vote attempts from your address. Please wait a minute and try again.",
                "vote_form": build_vote_form(poll),
            }
            response = TemplateResponse(request, self.form_partial, context)
            self._attach_token_cookie(response, poll)
            return response
        voter_token = _ensure_anon_token(request, poll)
        form = build_vote_form(poll, data=request.POST)

        context = {
            "poll": poll,
            "voter_token": voter_token,
            "has_voted": poll.has_voted(request.user, voter_token),
            "results_visible": poll.results_visible(request.user),
            "show_results": True,
        }

        if not form.is_valid():
            context["vote_form"] = form
            response = TemplateResponse(request, self.form_partial, context)
            self._attach_token_cookie(response, poll)
            return response

        try:
            if poll.is_ranked:
                poll.cast_vote(
                    user=request.user,
                    voter_token=voter_token,
                    rankings=form.rankings(),
                )
            else:
                poll.cast_vote(
                    user=request.user,
                    voter_token=voter_token,
                    choice_id=form.cleaned_data["choice"].id,
                )
        except (PollClosed, AlreadyVoted, InvalidVote) as exc:
            context["error"] = str(exc)
            context["vote_form"] = build_vote_form(poll)
            response = TemplateResponse(request, self.form_partial, context)
            self._attach_token_cookie(response, poll)
            return response

        context["has_voted"] = True
        context["just_voted"] = True
        messages.success(request, "Vote recorded.")
        response = TemplateResponse(request, self.template_partial, context)
        self._attach_token_cookie(response, poll)
        return response


class ResultsPartialView(View):
    """Return just the results partial — polled every few seconds by HTMX."""

    template_partial = "polls/partials/_results.html"
    frozen_partial = "polls/partials/_results_frozen.html"

    def get(self, request, slug):
        poll = get_object_or_404(Poll, slug=slug)
        visible = poll.results_visible(request.user)
        context = {
            "poll": poll,
            "results_visible": visible,
            "show_results": True,
        }
        template = self.template_partial if visible else self.frozen_partial
        return TemplateResponse(request, template, context)


class PollResultsView(DetailView):
    """Standalone full-page results view."""

    model = Poll
    template_name = "polls/poll_results_page.html"
    context_object_name = "poll"

    def get_object(self, queryset=None):
        return get_object_or_404(Poll, slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["results_visible"] = self.object.results_visible(self.request.user)
        ctx["show_results"] = True
        return ctx


# ---------------------------------------------------------------------------
# Widget, sharing, QR, freeze
# ---------------------------------------------------------------------------

class WidgetView(VoterTokenCookieMixin, DetailView):
    """Minimal, iframe-embeddable poll widget."""

    model = Poll
    template_name = "polls/poll_widget.html"
    context_object_name = "poll"

    def get_object(self, queryset=None):
        return get_object_or_404(Poll, slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        poll = self.object
        voter_token = _ensure_anon_token(self.request, poll)
        ctx["voter_token"] = voter_token
        ctx["has_voted"] = poll.has_voted(self.request.user, voter_token)
        ctx["results_visible"] = poll.results_visible(self.request.user)
        ctx["show_results"] = ctx["has_voted"] or poll.is_expired
        ctx["is_widget"] = True
        if not ctx["show_results"]:
            if poll.requires_auth and not self.request.user.is_authenticated:
                ctx["needs_login"] = True
            else:
                ctx["vote_form"] = build_vote_form(poll)
        return ctx

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        # Allow framing on any origin for the widget only.
        response.xframe_options_exempt = True
        response.csp_overrides = {"CSP_FRAME_ANCESTORS": "*"}
        # Persist the anonymous voter cookie if one was minted during the
        # context build. SameSite=Lax works for same-origin embedding (the
        # share-page preview); cross-origin embedding needs HTTPS +
        # SameSite=None;Secure in production.
        self._attach_token_cookie(response, self.object)
        return response


class ShareView(DetailView):
    """Share page: links + a QR image for the poll URL."""

    model = Poll
    template_name = "polls/poll_share.html"
    context_object_name = "poll"

    def get_object(self, queryset=None):
        return get_object_or_404(Poll, slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        slug = self.object.slug
        ctx["share_url"] = self.request.build_absolute_uri(reverse("polls:detail", args=[slug]))
        ctx["widget_url"] = self.request.build_absolute_uri(reverse("polls:widget", args=[slug]))
        ctx["qr_url"] = self.request.build_absolute_uri(reverse("polls:qr", args=[slug]))
        return ctx


class QRCodeView(View):
    """Generate and stream a QR PNG for the poll's share URL."""

    def get(self, request, slug):
        poll = get_object_or_404(Poll, slug=slug)
        share_url = request.build_absolute_uri(
            reverse("polls:detail", args=[poll.slug])
        )
        img = qrcode.make(share_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        response = HttpResponse(buf.getvalue(), content_type="image/png")
        response["Cache-Control"] = "public, max-age=3600"
        return response


class FreezeToggleView(LoginRequiredMixin, View):
    """Toggle the results_frozen flag. Owner or superuser only."""

    def post(self, request, slug):
        poll = get_object_or_404(Poll, slug=slug)
        if not (request.user == poll.created_by or request.user.is_superuser):
            messages.error(request, "Only the poll owner can freeze results.")
            return redirect("polls:detail", slug=poll.slug)
        poll.results_frozen = not poll.results_frozen
        poll.save(update_fields=["results_frozen"])
        action = "frozen" if poll.results_frozen else "unfrozen"
        messages.success(request, f"Results {action}.")
        return redirect("polls:detail", slug=poll.slug)
