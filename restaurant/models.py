import random
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.text import slugify

from core.modules import RESTAURANT_ROLE_CHOICES

TWO = Decimal("0.01")


def money(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


class Restaurant(models.Model):
    BUSINESS_TYPES = [
        ("restaurant", "Restaurant"),
        ("cafe", "Café"),
        ("cloud_kitchen", "Cloud kitchen"),
        ("hotel", "Hotel"),
        ("bar", "Bar & lounge"),
        ("bakery", "Bakery"),
        ("qsr", "QSR / chain"),
        ("food_court", "Food court"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    business_type = models.CharField(max_length=20, choices=BUSINESS_TYPES, default="restaurant")
    tagline = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=60, blank=True)
    gstin = models.CharField("GSTIN", max_length=20, blank=True)
    fssai = models.CharField("FSSAI licence", max_length=20, blank=True)
    logo_url = models.URLField(blank=True)
    cover_url = models.URLField(blank=True)
    opening_hours = models.CharField(max_length=120, blank=True, default="11:00 AM – 11:00 PM")

    is_active = models.BooleanField(default=True)
    access_granted = models.BooleanField(
        default=True, help_text="Super admin can switch off access without deleting data."
    )

    # Billing settings
    bill_footer = models.CharField(max_length=200, blank=True, default="Thank you! Visit again.")
    service_charge_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    round_off = models.BooleanField(default=True)
    charge_gst = models.BooleanField(default=False)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    loyalty_enabled = models.BooleanField(default=True)
    loyalty_points_per_100 = models.PositiveIntegerField(default=1)

    # Ordering channels
    qr_ordering_enabled = models.BooleanField(default=True)
    qr_auto_accept = models.BooleanField(default=False)
    online_ordering_enabled = models.BooleanField(default=True)
    accept_online_payment = models.BooleanField(default=False)
    accept_cash_on_delivery = models.BooleanField(default=True)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    delivery_radius_km = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("5.0"))
    min_order_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    # The restaurant's own Razorpay account for guest payments
    razorpay_key_id = models.CharField(max_length=60, blank=True)
    razorpay_key_secret = models.CharField(max_length=80, blank=True)

    # Online store SEO
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=170, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:120] or "restaurant"
            slug, n = base, 2
            while Restaurant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def owner(self):
        return self.staff.filter(role="owner").order_by("date_joined").first()

    @property
    def plan(self):
        sub = getattr(self, "subscription", None)
        return sub.plan if sub else None

    def has_feature(self, code):
        plan = self.plan
        return bool(plan and plan.has_feature(code))

    @property
    def half_gst_percent(self):
        return self.gst_percent / 2

    @property
    def online_payments_ready(self):
        return bool(self.accept_online_payment and self.razorpay_key_id and self.razorpay_key_secret)


class RolePermission(models.Model):
    """Per-restaurant override of which modules a role can open."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="role_permissions")
    role = models.CharField(max_length=20, choices=RESTAURANT_ROLE_CHOICES)
    modules = models.JSONField(default=list)

    class Meta:
        unique_together = ("restaurant", "role")

    def __str__(self):
        return f"{self.restaurant} · {self.role}"


# ------------------------------------------------------------------ menu
class Category(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    FOOD_TYPES = [("veg", "Veg"), ("non_veg", "Non-veg"), ("egg", "Egg")]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="menu_items")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="items")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=9, decimal_places=2)
    food_type = models.CharField(max_length=8, choices=FOOD_TYPES, default="veg")
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    show_online = models.BooleanField(default=True)
    hsn_code = models.CharField("HSN/SAC", max_length=12, blank=True)
    station = models.CharField(max_length=40, blank=True, help_text="Kitchen station, e.g. Main, Bar, Tandoor")
    image_url = models.URLField(blank=True)
    prep_minutes = models.PositiveIntegerField(default=15)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category__sort_order", "name"]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------- tables
class Area(models.Model):
    KINDS = [("dining", "Dining area"), ("room", "Hotel rooms")]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="areas")
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=KINDS, default="dining")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Table(models.Model):
    STATUS_CHOICES = [
        ("free", "Free"),
        ("occupied", "Occupied"),
        ("billed", "Billed"),
        ("reserved", "Reserved"),
        ("cleaning", "Cleaning"),
    ]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="tables")
    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True, related_name="tables")
    name = models.CharField(max_length=30)
    seats = models.PositiveIntegerField(default=4)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="free")
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="locked_tables"
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = ("restaurant", "name")

    def __str__(self):
        return self.name

    @property
    def open_order(self):
        return self.orders.filter(status__in=Order.OPEN_STATUSES).order_by("-created_at").first()


# ------------------------------------------------------------- customers
class Customer(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    birthday = models.DateField(null=True, blank=True)
    loyalty_points = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    visits = models.PositiveIntegerField(default=0)
    last_visit = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_visit", "-created_at"]
        unique_together = ("restaurant", "phone")

    def __str__(self):
        return self.name or self.phone

    @property
    def tier(self):
        spent = self.total_spent or 0
        if spent >= 25000:
            return "Gold"
        if spent >= 8000:
            return "Silver"
        return "Bronze"


# ---------------------------------------------------------------- orders
class Order(models.Model):
    TYPE_CHOICES = [
        ("dine_in", "Dine-in"),
        ("takeaway", "Takeaway"),
        ("delivery", "Delivery"),
        ("room", "Room service"),
    ]
    SOURCE_CHOICES = [("pos", "POS"), ("qr", "QR"), ("online", "Online")]
    STATUS_CHOICES = [
        ("awaiting", "Awaiting acceptance"),
        ("accepted", "Accepted"),
        ("preparing", "Preparing"),
        ("ready", "Ready"),
        ("served", "Served"),
        ("out_for_delivery", "Out for delivery"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("rejected", "Rejected"),
        ("merged", "Added to table order"),
    ]
    OPEN_STATUSES = ("awaiting", "accepted", "preparing", "ready", "served", "out_for_delivery")
    PAYMENT_STATUS = [("unpaid", "Unpaid"), ("partial", "Partly paid"), ("paid", "Paid")]
    DELIVERY_STATUS = [
        ("unassigned", "Unassigned"),
        ("assigned", "Rider assigned"),
        ("accepted", "Rider accepted"),
        ("picked", "Picked up"),
        ("delivered", "Delivered"),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="orders")
    number = models.CharField(max_length=20)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="dine_in")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="pos")
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    customer_name = models.CharField(max_length=120, blank=True)
    customer_phone = models.CharField(max_length=15, blank=True)
    delivery_address = models.TextField(blank=True)
    guests = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=255, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="accepted")
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS, default="unpaid")
    pay_online = models.BooleanField(default=False)
    razorpay_order_id = models.CharField(max_length=60, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    coupon_code = models.CharField(max_length=30, blank=True)
    service_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    bill_no = models.CharField(max_length=30, blank=True)
    billed_at = models.DateTimeField(null=True, blank=True)

    rider = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="deliveries"
    )
    delivery_status = models.CharField(max_length=12, choices=DELIVERY_STATUS, default="unassigned")
    delivery_otp = models.CharField(max_length=4, blank=True)

    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_orders"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders_taken"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["restaurant", "status"]), models.Index(fields=["restaurant", "created_at"])]

    def __str__(self):
        return f"#{self.number}"

    # -- helpers
    @classmethod
    def next_number(cls, restaurant):
        today = timezone.localdate()
        prefix = today.strftime("%d%m")
        qs = cls.objects.filter(restaurant=restaurant, number__startswith=prefix + "-")
        n = qs.count() + 1
        while qs.filter(number=f"{prefix}-{n:03d}").exists():
            n += 1
        return f"{prefix}-{n:03d}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = Order.next_number(self.restaurant)
        if self.order_type == "delivery" and not self.delivery_otp:
            self.delivery_otp = f"{random.randint(0, 9999):04d}"
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def active_items(self):
        return self.items.exclude(kot_status="cancelled")

    @property
    def half_tax(self):
        return money(self.tax / 2)

    @property
    def paid_amount(self):
        return self.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    @property
    def balance(self):
        return max(Decimal("0"), self.total - self.paid_amount)

    @property
    def place_label(self):
        if self.table_id:
            return self.table.name
        return self.get_order_type_display()

    @property
    def age_minutes(self):
        return int((timezone.now() - self.created_at).total_seconds() // 60)

    @property
    def age_display(self):
        mins = self.age_minutes
        if mins < 60:
            return f"{mins}m"
        return f"{mins // 60}h {mins % 60}m"

    @property
    def kitchen_status(self):
        statuses = set(self.active_items.values_list("kot_status", flat=True))
        if not statuses:
            return "Empty"
        if "pending" in statuses:
            return "Not sent"
        if statuses & {"new", "preparing"}:
            return "In kitchen"
        if "ready" in statuses:
            return "Ready"
        return "Served"

    def recalc(self, save=True):
        r = self.restaurant
        subtotal = sum((i.line_total for i in self.active_items), Decimal("0"))
        self.subtotal = money(subtotal)
        discount = min(money(self.discount), self.subtotal)
        taxable = self.subtotal - discount
        self.service_charge = money(taxable * r.service_charge_percent / 100) if self.order_type == "dine_in" else Decimal("0")
        self.tax = money((taxable + self.service_charge) * r.gst_percent / 100) if r.charge_gst else Decimal("0")
        if self.order_type == "delivery":
            self.delivery_fee = money(r.delivery_fee)
        else:
            self.delivery_fee = Decimal("0")
        gross = taxable + self.service_charge + self.tax + self.delivery_fee
        if r.round_off:
            rounded = gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            self.round_off = money(rounded - gross)
            self.total = money(rounded)
        else:
            self.round_off = Decimal("0")
            self.total = money(gross)
        if save:
            self.save()
        return self.total

    def refresh_payment_status(self):
        paid = self.paid_amount
        if paid <= 0:
            self.payment_status = "unpaid"
        elif paid >= self.total:
            self.payment_status = "paid"
        else:
            self.payment_status = "partial"


class OrderItem(models.Model):
    KOT_STATUS = [
        ("pending", "Not sent"),
        ("new", "New"),
        ("preparing", "Preparing"),
        ("ready", "Ready"),
        ("served", "Served"),
        ("cancelled", "Cancelled"),
    ]
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=9, decimal_places=2)
    qty = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=120, blank=True)
    food_type = models.CharField(max_length=8, default="veg")
    station = models.CharField(max_length=40, blank=True)
    kot_status = models.CharField(max_length=10, choices=KOT_STATUS, default="pending")
    kot_no = models.PositiveIntegerField(default=0)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.qty} × {self.name}"

    @property
    def line_total(self):
        return money(self.price * self.qty)


class Payment(models.Model):
    METHODS = [
        ("cash", "Cash"),
        ("upi", "UPI"),
        ("card", "Card"),
        ("razorpay", "Razorpay (online)"),
        ("wallet", "Wallet"),
        ("other", "Other"),
    ]
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=10, choices=METHODS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_method_display()} ₹{self.amount}"


class WaiterCall(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="waiter_calls")
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="waiter_calls")
    reason = models.CharField(max_length=60, default="Call waiter")
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ------------------------------------------------------------- inventory
class InventoryItem(models.Model):
    UNITS = [("kg", "kg"), ("g", "g"), ("l", "litre"), ("ml", "ml"), ("pcs", "pcs"), ("pack", "pack"), ("dozen", "dozen")]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="inventory_items")
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=6, choices=UNITS, default="kg")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    supplier = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_low(self):
        return self.quantity <= self.reorder_level

    @property
    def stock_value(self):
        return money(self.quantity * self.cost_per_unit)


class StockMovement(models.Model):
    REASONS = [("purchase", "Purchase"), ("usage", "Kitchen usage"), ("wastage", "Wastage"), ("adjust", "Adjustment")]
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name="movements")
    change = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.CharField(max_length=10, choices=REASONS, default="purchase")
    note = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ------------------------------------------------------------- marketing
class Coupon(models.Model):
    TYPES = [("percent", "Percent off"), ("flat", "Flat ₹ off")]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="coupons")
    code = models.CharField(max_length=30)
    description = models.CharField(max_length=140, blank=True)
    discount_type = models.CharField(max_length=8, choices=TYPES, default="percent")
    value = models.DecimalField(max_digits=8, decimal_places=2)
    min_order = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_discount = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="0 = no cap")
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    times_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("restaurant", "code")

    def __str__(self):
        return self.code

    def is_valid_for(self, subtotal):
        if not self.is_active:
            return False
        if self.valid_until and self.valid_until < timezone.localdate():
            return False
        return subtotal >= self.min_order

    def discount_for(self, subtotal):
        if not self.is_valid_for(subtotal):
            return Decimal("0")
        if self.discount_type == "percent":
            amount = subtotal * self.value / 100
        else:
            amount = self.value
        if self.max_discount:
            amount = min(amount, self.max_discount)
        return money(min(amount, subtotal))


# -------------------------------------------------------------- hardware
class Device(models.Model):
    KINDS = [
        ("bill_printer", "Bill printer (thermal)"),
        ("kot_printer", "KOT printer"),
        ("kds", "Kitchen display"),
        ("cash_drawer", "Cash drawer"),
        ("scanner", "Barcode scanner"),
        ("scale", "Weighing scale"),
        ("terminal", "Card / UPI terminal"),
        ("tablet", "POS tablet / display"),
    ]
    CONNECTIONS = [("usb", "USB"), ("lan", "LAN / Wi-Fi"), ("bluetooth", "Bluetooth"), ("browser", "Browser print")]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=15, choices=KINDS)
    connection = models.CharField(max_length=10, choices=CONNECTIONS, default="browser")
    address = models.CharField(max_length=80, blank=True, help_text="IP address or device name")
    paper_width = models.CharField(max_length=5, choices=[("58", "58 mm"), ("80", "80 mm")], default="80")
    station = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name
