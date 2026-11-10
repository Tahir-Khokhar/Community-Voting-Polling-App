"""URL routes for the polls app, served under the ``polls:`` namespace."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("create/", views.PollCreateView.as_view(), name="create"),
    path("<slug:slug>/", views.PollDetailView.as_view(), name="detail"),
    path("<slug:slug>/vote/", views.VoteView.as_view(), name="vote"),
    path("<slug:slug>/results/", views.ResultsPartialView.as_view(), name="results"),
    path(
        "<slug:slug>/results-page/",
        views.PollResultsView.as_view(),
        name="results_page",
    ),
    path("<slug:slug>/widget/", views.WidgetView.as_view(), name="widget"),
    path("<slug:slug>/share/", views.ShareView.as_view(), name="share"),
    path("<slug:slug>/qr.png", views.QRCodeView.as_view(), name="qr"),
    path("<slug:slug>/freeze/", views.FreezeToggleView.as_view(), name="freeze"),
]
