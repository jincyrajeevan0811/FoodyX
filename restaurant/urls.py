from django.urls import path

from . import views

app_name = "restaurant"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("calls/<int:pk>/resolve/", views.resolve_call, name="resolve_call"),

    # POS & tables
    path("pos/", views.pos, name="pos"),
    path("pos/new/<slug:kind>/", views.pos_new, name="pos_new"),
    path("pos/send/", views.pos_send, name="pos_send"),
    path("pos/table/<int:pk>/", views.pos_table, name="pos_table"),
    path("pos/table/<int:pk>/close/", views.pos_table_close, name="pos_table_close"),
    path("pos/table/<int:pk>/status/", views.pos_table_status, name="pos_table_status"),
    path("pos/order/<int:pk>/", views.pos_order, name="pos_order"),
    path("pos/order/<int:pk>/item/<int:item_pk>/cancel/", views.pos_item_cancel, name="pos_item_cancel"),
    path("pos/order/<int:pk>/serve/", views.pos_serve, name="pos_serve"),
    path("pos/order/<int:pk>/discount/", views.pos_discount, name="pos_discount"),
    path("pos/order/<int:pk>/bill/", views.pos_bill, name="pos_bill"),
    path("pos/order/<int:pk>/pay/", views.pos_pay, name="pos_pay"),
    path("pos/order/<int:pk>/complete/", views.pos_complete, name="pos_complete"),
    path("pos/order/<int:pk>/cancel/", views.pos_cancel_order, name="pos_cancel_order"),
    path("pos/order/<int:pk>/kot/<int:kot_no>/", views.kot_print, name="kot_print"),

    # Orders, bills
    path("live/", views.live_orders, name="live_orders"),
    path("orders/", views.orders, name="orders"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/accept/", views.order_accept, name="order_accept"),
    path("bills/", views.bills, name="bills"),
    path("bills/<int:pk>/", views.bill_print, name="bill_print"),

    # Kitchen, delivery
    path("kitchen/", views.kitchen, name="kitchen"),
    path("kitchen/<int:pk>/<int:kot_no>/", views.kitchen_advance, name="kitchen_advance"),
    path("delivery/", views.delivery, name="delivery"),
    path("delivery/<int:pk>/assign/", views.delivery_assign, name="delivery_assign"),
    path("rider/", views.rider, name="rider"),
    path("rider/toggle/", views.rider_toggle, name="rider_toggle"),
    path("rider/<int:pk>/", views.rider_action, name="rider_action"),

    # Menu
    path("menu/", views.menu, name="menu"),
    path("menu/items/add/", views.item_edit, name="item_add"),
    path("menu/items/<int:pk>/", views.item_edit, name="item_edit"),
    path("menu/items/<int:pk>/toggle/", views.item_toggle, name="item_toggle"),
    path("menu/items/<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("menu/items/bulk/", views.items_bulk, name="items_bulk"),
    path("menu/items/import/", views.items_import, name="items_import"),
    path("menu/categories/add/", views.category_edit, name="category_add"),
    path("menu/categories/<int:pk>/", views.category_edit, name="category_edit"),

    # Tables
    path("tables/", views.tables, name="tables"),
    path("tables/add/", views.table_edit, name="table_add"),
    path("tables/bulk/", views.tables_bulk_add, name="tables_bulk_add"),
    path("tables/qr/", views.tables_qr, name="tables_qr"),
    path("tables/<int:pk>/", views.table_edit, name="table_edit"),
    path("areas/add/", views.area_edit, name="area_add"),
    path("areas/<int:pk>/", views.area_edit, name="area_edit"),

    # Customers, inventory, reports, marketing
    path("customers/", views.customers, name="customers"),
    path("customers/add/", views.customer_edit, name="customer_add"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("inventory/", views.inventory, name="inventory"),
    path("inventory/add/", views.inventory_edit, name="inventory_add"),
    path("inventory/<int:pk>/", views.inventory_edit, name="inventory_edit"),
    path("inventory/<int:pk>/move/", views.inventory_move, name="inventory_move"),
    path("reports/", views.reports, name="reports"),
    path("marketing/", views.marketing, name="marketing"),
    path("marketing/coupons/add/", views.coupon_edit, name="coupon_add"),
    path("marketing/coupons/<int:pk>/", views.coupon_edit, name="coupon_edit"),

    # Setup
    path("staff/", views.staff, name="staff"),
    path("staff/add/", views.staff_edit, name="staff_add"),
    path("staff/permissions/", views.staff_permissions, name="staff_permissions"),
    path("staff/<int:pk>/", views.staff_edit, name="staff_edit"),
    path("staff/<int:pk>/toggle/", views.staff_toggle, name="staff_toggle"),
    path("hardware/", views.hardware, name="hardware"),
    path("hardware/add/", views.device_edit, name="device_add"),
    path("hardware/<int:pk>/", views.device_edit, name="device_edit"),
    path("hardware/<int:pk>/test/", views.device_test, name="device_test"),
    path("settings/", views.settings_view, name="settings"),
    path("billing/", views.billing, name="billing"),
    path("billing/checkout/", views.billing_checkout, name="billing_checkout"),
    path("billing/<int:pk>/verify/", views.billing_verify, name="billing_verify"),
    path("billing/<int:pk>/invoice/", views.billing_invoice, name="billing_invoice"),
]
