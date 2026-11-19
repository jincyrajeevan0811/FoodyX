from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup, name="signup"),
    path("go/", views.home_redirect, name="home_redirect"),
    path("account/", views.profile, name="profile"),
    path("legal/<slug:page>/", views.legal, name="legal"),
]
