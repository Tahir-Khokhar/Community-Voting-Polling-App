"""Root URL configuration for the Community Voting & Polling App."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from polls.views import SignUpView

urlpatterns = [
    path("admin/", admin.site.urls),
    # /favicon.ico 301s to the static asset so browsers stop 404ing the root
    # favicon on every page (base.html also links the redirect target).
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/favicon.ico", permanent=True),
    ),
    # Registration sits next to the built-in auth views; it must be listed
    # before the auth include() so its name is ours, not the fallback's.
    path("accounts/signup/", SignUpView.as_view(), name="signup"),
    # Built-in auth views (login/logout/password change/reset) under /accounts/.
    path("accounts/", include("django.contrib.auth.urls")),
    # The polls app owns the root namespace.
    path("", include(("polls.urls", "polls"), namespace="polls")),
]
