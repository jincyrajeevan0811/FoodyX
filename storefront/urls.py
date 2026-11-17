from django.urls import path

from saas.views import razorpay_webhook

from . import views

app_name = "storefront"

urlpatterns = [
    path("t/<uuid:token>/", views.table_menu, name="table_menu"),
    path("t/<uuid:token>/order/", views.table_order, name="table_order"),
    path("t/<uuid:token>/call/", views.call_waiter, name="call_waiter"),
    path("s/<slug:slug>/", views.store, name="store"),
    path("s/<slug:slug>/checkout/", views.store_checkout, name="store_checkout"),
    path("o/<uuid:public_id>/", views.track, name="track"),
    path("o/<uuid:public_id>/pay/", views.pay, name="pay"),
    path("o/<uuid:public_id>/pay/verify/", views.pay_verify, name="pay_verify"),
    path("webhooks/razorpay/", razorpay_webhook, name="razorpay_webhook"),
]
