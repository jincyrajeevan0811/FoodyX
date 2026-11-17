"""Roles, modules and default permissions used across FoodyX."""

# ---------------------------------------------------------------- roles
PLATFORM_ROLES = ("super_admin", "platform_admin", "platform_support")
RESTAURANT_ROLES = (
    "owner", "admin", "manager", "captain", "cashier", "kitchen", "rider", "store_keeper",
)

ROLE_CHOICES = [
    ("super_admin", "Super admin"),
    ("platform_admin", "Platform admin"),
    ("platform_support", "Platform support"),
    ("owner", "Owner"),
    ("admin", "Admin"),
    ("manager", "Manager"),
    ("captain", "Captain (waiter)"),
    ("cashier", "Cashier"),
    ("kitchen", "Kitchen"),
    ("rider", "Rider"),
    ("store_keeper", "Store keeper"),
]
ROLE_LABELS = dict(ROLE_CHOICES)

RESTAURANT_ROLE_CHOICES = [(r, ROLE_LABELS[r]) for r in RESTAURANT_ROLES]
PLATFORM_ROLE_CHOICES = [(r, ROLE_LABELS[r]) for r in PLATFORM_ROLES]

ROLE_DESCRIPTIONS = {
    "owner": "Everything: orders, billing, reports, menu, staff, settings. Can open any table.",
    "admin": "Full restaurant administration, same reach as the owner.",
    "manager": "Runs the floor: orders, billing, discounts, cancelling items, reports, menu.",
    "captain": "Takes table orders and sends them to the kitchen.",
    "cashier": "Prints bills, takes payment, gives discounts.",
    "kitchen": "Sees the kitchen screen and marks food as preparing / ready.",
    "rider": "Sees delivery orders, collects cash on delivery, confirms with OTP.",
    "store_keeper": "Manages stock and purchases.",
}

# -------------------------------------------------------------- modules
# code, label, lucide icon, nav group, url name
MODULES = [
    ("dashboard", "Dashboard", "layout-dashboard", "Operate", "restaurant:dashboard"),
    ("pos", "POS & Tables", "monitor-smartphone", "Operate", "restaurant:pos"),
    ("live_orders", "Live Orders", "radio", "Operate", "restaurant:live_orders"),
    ("orders", "Orders", "clipboard-list", "Operate", "restaurant:orders"),
    ("bills", "Bills", "receipt-text", "Operate", "restaurant:bills"),
    ("kitchen", "Kitchen Display", "chef-hat", "Operate", "restaurant:kitchen"),
    ("delivery", "Home Delivery", "bike", "Operate", "restaurant:delivery"),
    ("rider", "Rider", "navigation", "Operate", "restaurant:rider"),
    ("menu", "Menu", "utensils-crossed", "Manage", "restaurant:menu"),
    ("tables", "Tables & Rooms", "layout-grid", "Manage", "restaurant:tables"),
    ("customers", "Customers & Loyalty", "users", "Manage", "restaurant:customers"),
    ("inventory", "Inventory", "package", "Manage", "restaurant:inventory"),
    ("reports", "Reports & Insights", "bar-chart-3", "Manage", "restaurant:reports"),
    ("marketing", "Marketing & SEO", "megaphone", "Manage", "restaurant:marketing"),
    ("staff", "Staff & Roles", "shield-check", "Setup", "restaurant:staff"),
    ("hardware", "Hardware", "printer", "Setup", "restaurant:hardware"),
    ("settings", "Settings", "settings", "Setup", "restaurant:settings"),
    ("billing", "Plan & Billing", "credit-card", "Setup", "restaurant:billing"),
]
MODULE_CODES = [m[0] for m in MODULES]
MODULE_LABELS = {m[0]: m[1] for m in MODULES}

# Features that a subscription plan switches on or off. Anything not listed
# here is part of every plan.
PLAN_FEATURES = [
    ("kitchen", "Kitchen display system"),
    ("delivery", "Home delivery management"),
    ("rider", "Rider app with OTP & COD"),
    ("customers", "Customers & loyalty"),
    ("inventory", "Inventory & stock"),
    ("marketing", "Marketing, coupons & SEO"),
    ("qr_ordering", "QR table ordering"),
    ("online_store", "Online ordering website"),
    ("online_payments", "Online payments via Razorpay"),
    ("split_billing", "Split billing"),
    ("insights", "Smart insights"),
    ("multi_area", "Rooms & multiple areas"),
]
PLAN_FEATURE_CODES = [f[0] for f in PLAN_FEATURES]
PLAN_FEATURE_LABELS = dict(PLAN_FEATURES)

ALL_MODULES = set(MODULE_CODES)

DEFAULT_ROLE_MODULES = {
    "owner": ALL_MODULES,
    "admin": ALL_MODULES,
    "manager": ALL_MODULES - {"billing", "staff", "rider"},
    "captain": {"dashboard", "pos", "live_orders", "orders", "kitchen"},
    "cashier": {"dashboard", "pos", "live_orders", "orders", "bills", "customers"},
    "kitchen": {"kitchen"},
    "rider": {"rider"},
    "store_keeper": {"inventory", "menu"},
}
# Owners can never lose these, otherwise they could lock themselves out.
LOCKED_OWNER_MODULES = {"dashboard", "staff", "settings", "billing"}

# Roles allowed to do sensitive things inside a module
CAN_CANCEL_ITEMS = {"owner", "admin", "manager"}
CAN_DISCOUNT = {"owner", "admin", "manager", "cashier"}
CAN_OVERRIDE_TABLE_LOCK = {"owner", "admin"}
SINGLE_DEVICE_ROLES = {"captain"}
