"""
Forms for the polls app.

Two concerns:
  * Creating a poll + its choices (``PollCreateForm`` paired with an inline
    ``ChoiceFormSet``).
  * Casting a vote — a small dynamic form per poll that adapts to single vs.
    ranked voting. Voting is not a ModelForm: the actual write goes through
    ``Poll.cast_vote()`` so the race-safe counter update stays in one place.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import Choice, Poll


class PollCreateForm(forms.ModelForm):
    """Top-level poll fields. Choices are added via the inline formset below."""

    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Optional. Interpreted in the app's timezone (Pakistan "
        "Standard Time, UTC+5). Leave blank for a poll that never expires.",
    )

    class Meta:
        model = Poll
        fields = ("title", "description", "poll_type", "voting_mode", "expires_at")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ask a question..."}),
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional context for voters"}
            ),
        }

    def clean_expires_at(self):
        value = self.cleaned_data.get("expires_at")
        if value and value <= timezone.now():
            raise forms.ValidationError("Expiry must be in the future.")
        return value


# Inline formset for choices. At least two choices are required for a poll to
# be meaningful; voters can't rank a single option.
ChoiceFormSet = inlineformset_factory(
    Poll,
    Choice,
    fields=("text",),
    extra=4,
    min_num=2,
    validate_min=True,
    can_delete=False,
    widgets={"text": forms.TextInput(attrs={"placeholder": "Choice text"})},
    labels={"text": ""},
)


class SingleVoteForm(forms.Form):
    """A radio-select form for single-choice polls."""

    choice = forms.ModelChoiceField(
        queryset=None,
        empty_label=None,
        widget=forms.RadioSelect(attrs={"class": "vote-radio"}),
    )

    def __init__(self, *args, poll=None, **kwargs):
        super().__init__(*args, **kwargs)
        if poll is not None:
            self.fields["choice"].queryset = poll.choices.all()


class RankedVoteForm(forms.Form):
    """
    A form with one select per choice, offering ranks 1..N.

    Built dynamically from the poll's choices so the field labels match the
    actual choice text. ``rankings()`` returns the ``{choice_id: rank}`` dict
    that ``Poll.cast_vote()`` expects.
    """

    def __init__(self, *args, poll=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._poll = poll
        if poll is None:
            return
        self._choices = list(poll.choices.all())
        n = len(self._choices)
        rank_options = [(str(i), str(i)) for i in range(1, n + 1)]
        for choice in self._choices:
            self.fields[f"choice_{choice.id}"] = forms.ChoiceField(
                label=choice.text,
                choices=rank_options,
                widget=forms.Select(attrs={"class": "rank-select"}),
            )

    def clean(self):
        cleaned = super().clean()
        if self._poll is None:
            return cleaned
        ranks = [int(v) for v in cleaned.values() if v]
        n = len(self._choices)
        expected = list(range(1, n + 1))
        if sorted(ranks) != expected:
            raise forms.ValidationError(
                "Please assign each rank 1..%d exactly once, with no repeats." % n
            )
        return cleaned

    def rankings(self):
        """Return ``{choice_id: rank}`` from cleaned data."""
        return {
            int(field_name.split("_", 1)[1]): int(value)
            for field_name, value in self.cleaned_data.items()
            if field_name.startswith("choice_")
        }


def vote_form_class(poll):
    """Return the right form class for a poll."""
    return RankedVoteForm if poll.is_ranked else SingleVoteForm


def build_vote_form(poll, data=None):
    """Instantiate the correct vote form bound (or unbound) for ``poll``."""
    cls = vote_form_class(poll)
    return cls(data=data, poll=poll)


class SignUpForm(UserCreationForm):
    """
    Registration form: username + email + password, with Django's default
    password validators (minimum length, common-password, all-numeric).

    Input styling comes from the global form-control CSS in ``base.html``;
    the widgets only carry placeholders and autocomplete hints here.
    """

    email = forms.EmailField(
        required=True,
        help_text="Used for account emails such as password reset.",
    )

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "e.g. jane_doe", "autocapitalize": "none", "autocomplete": "username"}
        )
        self.fields["email"].widget.attrs.update(
            {"placeholder": "you@example.com", "autocomplete": "email"}
        )
        self.fields["password1"].widget.attrs.update(
            {"placeholder": "At least 8 characters", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"placeholder": "Repeat the password", "autocomplete": "new-password"}
        )
