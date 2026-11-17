from .dashboard import dashboard, resolve_call  # noqa: F401
from .delivery import delivery, delivery_assign, rider, rider_action, rider_toggle  # noqa: F401
from .kitchen import kitchen, kitchen_advance  # noqa: F401
from .manage import (  # noqa: F401
    coupon_edit, customer_detail, customer_edit, customers, inventory, inventory_edit, inventory_move,
    marketing, reports,
)
from .menu import category_edit, item_delete, item_edit, item_toggle, items_bulk, items_import, menu  # noqa: F401
from .orders import bill_print, bills, live_orders, order_accept, order_detail, orders  # noqa: F401
from .pos import (  # noqa: F401
    kot_print, pos, pos_bill, pos_cancel_order, pos_complete, pos_discount, pos_item_cancel, pos_new, pos_order, pos_pay,
    pos_send, pos_serve, pos_table, pos_table_close, pos_table_status,
)
from .setup import (  # noqa: F401
    billing, billing_checkout, billing_invoice, billing_verify, device_edit, device_test, hardware,
    settings_view, staff, staff_edit, staff_permissions, staff_toggle,
)
from .tables import area_edit, table_edit, tables, tables_bulk_add, tables_qr  # noqa: F401
