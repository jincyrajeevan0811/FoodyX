from django import forms
from django.contrib.auth import get_user_model

from core.forms import _clean_unique_email, _clean_unique_phone
from core.modules import PLAN_FEATURES, PLATFORM_ROLE_CHOICES, RESTAURANT_ROLE_CHOICES
from restaurant.models import Restaurant

from .models import Plan, PlatformPayment, PlatformSettings, Subscription

User = get_user_model()


class PlanForm(forms.ModelForm):
    features = forms.MultipleChoiceField(
        choices=PLAN_FEATURES, widget=forms.CheckboxSelectMultiple, required=False,
        help_text="Modules and features restaurants on this plan can use.",
    )

    class Meta:
        model = Plan
        fields = [
            "name", "tagline", "price_monthly", "price_yearly", "is_custom_pricing", "trial_days",
            "max_staff", "max_tables", "max_devices", "features", "highlights",
            "is_popular", "is_public", "is_active", "sort_order",
        ]
        widgets = {"highlights": forms.Textarea(attrs={"rows": 6, "placeholder": "10 staff logins\nQR table ordering\n..."})}


class OnboardRestaurantForm(forms.Form):
    name = forms.CharField(label="Restaurant name", max_length=120)
    business_type = forms.ChoiceField(choices=Restaurant.BUSINESS_TYPES)
    city = forms.CharField(max_length=60, required=False)
    owner_name = forms.CharField(max_length=120)
    phone = forms.CharField(label="Owner mobile", max_length=15)
    email = forms.EmailField(label="Owner email")
    password = forms.CharField(min_length=6, help_text="The owner signs in with their mobile or email and this password.")
    plan = forms.ModelChoiceField(queryset=Plan.objects.filter(is_active=True))
    start_as = forms.ChoiceField(choices=[("trial", "Free trial"), ("active", "Paid & active")], initial="trial")
    billing_cycle = forms.ChoiceField(choices=Subscription.CYCLE_CHOICES, initial="monthly")
    trial_days = forms.IntegerField(min_value=1, max_value=365, initial=14)
    access_granted = forms.BooleanField(initial=True, required=False, label="Grant access now")
    send_welcome = forms.BooleanField(initial=True, required=False, label="Email the login details to the owner")

    def clean_phone(self):
        phone = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit() or ch == "+")
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError("This mobile number already has a login.")
        return phone

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email already has a login.")
        return email


class RestaurantEditForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["name", "business_type", "phone", "email", "city", "address", "gstin", "fssai", "is_active", "access_granted"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class SubscriptionForm(forms.ModelForm):
    current_period_end = forms.DateTimeField(
        label="Valid until", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    class Meta:
        model = Subscription
        fields = ["plan", "status", "billing_cycle", "current_period_end", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class ManualPaymentForm(forms.ModelForm):
    restaurant = forms.ModelChoiceField(queryset=Restaurant.objects.all())
    activate_subscription = forms.BooleanField(
        required=False, initial=True, label="Mark paid and extend the subscription now"
    )

    class Meta:
        model = PlatformPayment
        fields = ["restaurant", "plan", "billing_cycle", "amount", "method", "reference"]
        widgets = {"billing_cycle": forms.Select(choices=Subscription.CYCLE_CHOICES)}


class TeamMemberForm(forms.ModelForm):
    role = forms.ChoiceField(choices=PLATFORM_ROLE_CHOICES)
    password = forms.CharField(required=False, min_length=6, help_text="Leave empty to keep the current password.")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "is_active"]

    def clean_phone(self):
        return self.cleaned_data.get("phone") or None

    def clean(self):
        data = super().clean()
        if not self.instance.pk and not data.get("password"):
            self.add_error("password", "Set a password for the new team member.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.restaurant = None
        user.is_staff = user.role in ("super_admin", "platform_admin")
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


SETTINGS_SECTIONS = [
    ("general", "General", ["site_name", "site_url", "support_email", "support_phone", "sales_email", "allow_self_signup", "default_trial_days"]),
    ("payments", "Payments (Razorpay)", ["razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret", "gst_percent"]),
    ("email", "Email (SMTP)", ["smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_use_tls", "smtp_from_email"]),
    ("company", "Company & invoices", ["company_name", "company_gstin", "company_address"]),
    ("seo", "SEO", ["seo_title", "seo_description", "google_site_verification"]),
]


class PlatformSettingsForm(forms.ModelForm):
    class Meta:
        model = PlatformSettings
        fields = [f for _, _, fields in SETTINGS_SECTIONS for f in fields]
        widgets = {
            "razorpay_key_secret": forms.PasswordInput(render_value=True),
            "razorpay_webhook_secret": forms.PasswordInput(render_value=True),
            "smtp_password": forms.PasswordInput(render_value=True),
            "company_address": forms.Textarea(attrs={"rows": 3}),
            "seo_description": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "razorpay_webhook_secret": "Webhook URL to paste in Razorpay: <your site>/webhooks/razorpay/",
            "google_site_verification": "The content value of the google-site-verification meta tag.",
        }

    def sections(self):
        return [(key, title, [self[f] for f in fields]) for key, title, fields in SETTINGS_SECTIONS]


class UserAdminForm(forms.ModelForm):
    """Super admin editing any login: name, contact, role, status, password."""

    role = forms.ChoiceField()
    password = forms.CharField(
        required=False, min_length=6, widget=forms.PasswordInput(render_value=False),
        label="New password", help_text="Leave empty to keep the current password.",
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "is_active"]
        labels = {"phone": "Mobile number (sign-in)", "is_active": "Login is active"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["role"].choices = RESTAURANT_ROLE_CHOICES if self.instance.restaurant_id else PLATFORM_ROLE_CHOICES

    def clean_phone(self):
        return _clean_unique_phone(self, self.cleaned_data.get("phone"))

    def clean_email(self):
        return _clean_unique_email(self, self.cleaned_data.get("email"))

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user
