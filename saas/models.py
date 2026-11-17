from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from core.modules import PLAN_FEATURE_LABELS


class Plan(models.Model):
    """A subscription tier sold to restaurants (e.g. Basic, Average, Medium)."""

    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    tagline = models.CharField(max_length=140, blank=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_custom_pricing = models.BooleanField(
        default=False, help_text="Shows 'Let's talk' instead of a price (enterprise)."
    )
    max_staff = models.PositiveIntegerField(default=3, help_text="0 = unlimited")
    max_tables = models.PositiveIntegerField(default=15, help_text="0 = unlimited")
    max_devices = models.PositiveIntegerField(default=2, help_text="0 = unlimited")
    features = models.JSONField(default=list, blank=True, help_text="Feature codes switched on")
    highlights = models.TextField(blank=True, help_text="One bullet per line, shown on pricing cards")
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True, help_text="Show on the public pricing page")
    trial_days = models.PositiveIntegerField(default=14)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "price_monthly"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "plan"
            slug, n = base, 2
            while Plan.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def highlight_list(self):
        return [h.strip() for h in self.highlights.splitlines() if h.strip()]

    @property
    def feature_labels(self):
        return [PLAN_FEATURE_LABELS[f] for f in self.features if f in PLAN_FEATURE_LABELS]

    def has_feature(self, code):
        return code in (self.features or [])

    def price_for(self, cycle):
        return self.price_yearly if cycle == "yearly" else self.price_monthly

    @property
    def yearly_monthly_equivalent(self):
        if not self.price_yearly:
            return Decimal("0")
        return (self.price_yearly / 12).quantize(Decimal("1"))


class Subscription(models.Model):
    STATUS_CHOICES = [
        ("trial", "Trial"),
        ("active", "Active"),
        ("past_due", "Past due"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ]
    CYCLE_CHOICES = [("monthly", "Monthly"), ("yearly", "Yearly")]

    restaurant = models.OneToOneField(
        "restaurant.Restaurant", on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="trial")
    billing_cycle = models.CharField(max_length=10, choices=CYCLE_CHOICES, default="monthly")
    started_at = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.restaurant} · {self.plan} ({self.get_status_display()})"

    @property
    def is_trial(self):
        return self.status == "trial"

    @property
    def is_live(self):
        return self.status in ("trial", "active") and self.current_period_end >= timezone.now()

    @property
    def days_left(self):
        delta = self.current_period_end - timezone.now()
        return max(0, delta.days + (1 if delta.seconds > 0 else 0))

    @property
    def effective_status(self):
        if self.status in ("trial", "active") and self.current_period_end < timezone.now():
            return "expired"
        return self.status

    @property
    def monthly_value(self):
        """Contribution to MRR (excl. GST)."""
        if self.status != "active" or not self.is_live:
            return Decimal("0")
        if self.billing_cycle == "yearly":
            return (self.plan.price_yearly / 12).quantize(Decimal("0.01"))
        return self.plan.price_monthly

    def start_trial(self, days=None):
        days = days if days is not None else self.plan.trial_days
        self.status = "trial"
        self.started_at = timezone.now()
        self.current_period_end = timezone.now() + timedelta(days=days)

    def activate(self, cycle="monthly"):
        """Start or extend a paid period."""
        now = timezone.now()
        base = self.current_period_end if (self.status == "active" and self.current_period_end > now) else now
        self.billing_cycle = cycle
        self.status = "active"
        self.current_period_end = base + timedelta(days=365 if cycle == "yearly" else 30)


class PlatformPayment(models.Model):
    STATUS_CHOICES = [("created", "Created"), ("paid", "Paid"), ("failed", "Failed"), ("refunded", "Refunded")]
    METHOD_CHOICES = [
        ("razorpay", "Razorpay"),
        ("bank", "Bank transfer"),
        ("upi", "UPI"),
        ("cash", "Cash"),
        ("cheque", "Cheque"),
        ("other", "Other"),
    ]

    restaurant = models.ForeignKey(
        "restaurant.Restaurant", on_delete=models.CASCADE, related_name="platform_payments"
    )
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True)
    billing_cycle = models.CharField(max_length=10, default="monthly")
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Excl. GST")
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="created")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default="razorpay")
    razorpay_order_id = models.CharField(max_length=60, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=60, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    invoice_no = models.CharField(max_length=30, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.restaurant} · ₹{self.total} · {self.status}"

    def mark_paid(self, payment_id="", method=None):
        """Mark paid once and extend the subscription. Safe to call twice."""
        if self.status == "paid":
            return False
        self.status = "paid"
        self.paid_at = timezone.now()
        if payment_id:
            self.razorpay_payment_id = payment_id
        if method:
            self.method = method
        if not self.invoice_no:
            count = PlatformPayment.objects.filter(status="paid").count() + 1
            self.invoice_no = f"FX-{timezone.now():%Y%m}-{count:04d}"
        self.save()
        sub = getattr(self.restaurant, "subscription", None)
        if sub is None:
            sub = Subscription(restaurant=self.restaurant, plan=self.plan, current_period_end=timezone.now())
        if self.plan:
            sub.plan = self.plan
        sub.activate(self.billing_cycle)
        sub.save()
        return True


class PlatformSettings(models.Model):
    """Singleton with the platform-wide configuration."""

    site_name = models.CharField(max_length=60, default="FoodyX")
    site_url = models.URLField(blank=True)
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=20, blank=True)
    sales_email = models.EmailField(blank=True)
    allow_self_signup = models.BooleanField(default=True)
    default_trial_days = models.PositiveIntegerField(default=14)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))

    razorpay_key_id = models.CharField(max_length=60, blank=True)
    razorpay_key_secret = models.CharField(max_length=80, blank=True)
    razorpay_webhook_secret = models.CharField(max_length=80, blank=True)

    smtp_host = models.CharField(max_length=120, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=120, blank=True)
    smtp_password = models.CharField(max_length=120, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_from_email = models.EmailField(blank=True)

    company_name = models.CharField(max_length=120, blank=True)
    company_gstin = models.CharField("Company GSTIN", max_length=20, blank=True)
    company_address = models.TextField(blank=True)

    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=170, blank=True)
    google_site_verification = models.CharField(max_length=120, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform settings"
        verbose_name_plural = "Platform settings"

    def __str__(self):
        return "Platform settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def razorpay_ready(self):
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def smtp_ready(self):
        return bool(self.smtp_host and self.smtp_from_email)

    def checklist(self):
        return [
            ("Site address set", bool(self.site_url), "general"),
            ("Razorpay keys added", self.razorpay_ready, "payments"),
            ("Razorpay webhook secret", bool(self.razorpay_webhook_secret), "payments"),
            ("Email (SMTP) configured", self.smtp_ready, "email"),
            ("Support contact", bool(self.support_email or self.support_phone), "general"),
            ("Company GSTIN for invoices", bool(self.company_gstin), "company"),
            ("SEO title & description", bool(self.seo_title and self.seo_description), "seo"),
            ("Google Search Console verified", bool(self.google_site_verification), "seo"),
        ]


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities"
    )
    restaurant = models.ForeignKey(
        "restaurant.Restaurant", null=True, blank=True, on_delete=models.CASCADE, related_name="activities"
    )
    action = models.CharField(max_length=80)
    detail = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} by {self.actor}"
