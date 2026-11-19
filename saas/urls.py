from django.urls import path

from . import views

app_name = "saas"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("restaurants/", views.restaurants, name="restaurants"),
    path("restaurants/add/", views.restaurant_add, name="restaurant_add"),
    path("restaurants/<int:pk>/", views.restaurant_detail, name="restaurant_detail"),
    path("restaurants/<int:pk>/action/", views.restaurant_action, name="restaurant_action"),
    path("restaurants/<int:pk>/permissions/", views.restaurant_permissions, name="restaurant_permissions"),
    path("plans/", views.plans, name="plans"),
    path("plans/add/", views.plan_edit, name="plan_add"),
    path("plans/<int:pk>/", views.plan_edit, name="plan_edit"),
    path("plans/<int:pk>/delete/", views.plan_delete, name="plan_delete"),
    path("payments/", views.payments, name="payments"),
    path("payments/add/", views.payment_add, name="payment_add"),
    path("payments/<int:pk>/invoice/", views.invoice, name="invoice"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/toggle/", views.user_toggle, name="user_toggle"),
    path("team/", views.team, name="team"),
    path("team/add/", views.team_edit, name="team_add"),
    path("team/<int:pk>/", views.team_edit, name="team_edit"),
    path("activity/", views.activity, name="activity"),
    path("settings/", views.settings_view, name="settings"),
    path("health/", views.health, name="health"),
]
