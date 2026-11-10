"""Root URL configuration for the Community Voting & Polling App."""

from django.contrib import admin
from django.urls import include, path

from polls.views import SignUpView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Registration sits next to the built-in auth views; it must be listed
    # before the auth include() so its name is ours, not the fallback's.
    path("accounts/signup/", SignUpView.as_view(), name="signup"),
    # Built-in auth views (login/logout/password change/reset) under /accounts/.
    path("accounts/", include("django.contrib.auth.urls")),
    # The polls app owns the root namespace.
    path("", include(("polls.urls", "polls"), namespace="polls")),
]
