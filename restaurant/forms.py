from django import forms
from django.contrib.auth import get_user_model

from core.modules import RESTAURANT_ROLE_CHOICES

from .models import (
    Area, Category, Coupon, Customer, Device, InventoryItem, MenuItem, Restaurant, StockMovement, Table,
)

User = get_user_model()


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = ["name", "category", "price", "food_type", "description", "station", "hsn_code",
                  "prep_minutes", "image_url", "is_available", "is_featured", "show_online"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, restaurant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(restaurant=restaurant)


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "sort_order", "is_active"]


class AreaForm(forms.ModelForm):
    class Meta:
        model = Area
        fields = ["name", "kind", "sort_order"]


class TableForm(forms.ModelForm):
    class Meta:
        model = Table
        fields = ["name", "area", "seats", "sort_order"]

    def __init__(self, *args, restaurant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        self.fields["area"].queryset = Area.objects.filter(restaurant=restaurant)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Table.objects.filter(restaurant=self.restaurant, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A table with this name already exists.")
        return name


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "birthday", "address", "loyalty_points", "notes"]
        widgets = {"birthday": forms.DateInput(attrs={"type": "date"}), "address": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, restaurant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant

    def clean_phone(self):
        phone = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit() or ch == "+")
        qs = Customer.objects.filter(restaurant=self.restaurant, phone=phone)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A customer with this number already exists.")
        return phone


class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ["name", "unit", "quantity", "reorder_level", "cost_per_unit", "supplier"]


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ["change", "reason", "note"]
        labels = {"change": "Quantity (use minus for usage/wastage)"}


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ["code", "description", "discount_type", "value", "min_order", "max_discount", "valid_until", "is_active"]
        widgets = {"valid_until": forms.DateInput(attrs={"type": "date"})}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "kind", "connection", "address", "paper_width", "station", "is_active"]


class StaffForm(forms.ModelForm):
    role = forms.ChoiceField(choices=[c for c in RESTAURANT_ROLE_CHOICES if c[0] != "owner"])
    password = forms.CharField(required=False, min_length=6, widget=forms.PasswordInput(render_value=False),
                               help_text="Leave empty to keep the current password.")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "email", "role", "pin", "is_active"]
        labels = {"phone": "Mobile number (used to sign in)", "pin": "4-digit quick-switch PIN"}

    def __init__(self, *args, restaurant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.restaurant = restaurant
        self.fields["phone"].required = True
        self.fields["first_name"].required = True
        if self.instance.pk and self.instance.role == "owner":
            self.fields["role"].choices = RESTAURANT_ROLE_CHOICES
            self.fields["role"].disabled = True

    def clean_phone(self):
        phone = "".join(ch for ch in (self.cleaned_data.get("phone") or "") if ch.isdigit() or ch == "+")
        qs = User.objects.filter(phone=phone)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This mobile number already has a login.")
        return phone or None

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").lower()

    def clean_pin(self):
        pin = self.cleaned_data.get("pin") or ""
        if pin and (len(pin) != 4 or not pin.isdigit()):
            raise forms.ValidationError("PIN must be 4 digits.")
        if pin and User.objects.filter(restaurant=self.restaurant, pin=pin).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another staff member already uses this PIN.")
        return pin

    def clean(self):
        data = super().clean()
        if not self.instance.pk and not data.get("password"):
            self.add_error("password", "Set a password for the new login.")
        return data

    def save(self, commit=True):
        from saas.services import unique_username

        user = super().save(commit=False)
        user.restaurant = self.restaurant
        if not user.username:
            user.username = unique_username(f"{user.first_name}.{self.restaurant.slug}"[:24])
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


SETTINGS_SECTIONS = [
    ("profile", "Restaurant profile", ["name", "business_type", "tagline", "phone", "email", "address", "city",
                                        "opening_hours", "logo_url", "cover_url", "gstin", "fssai"]),
    ("billing", "Billing & tax", ["bill_footer", "service_charge_percent", "round_off", "charge_gst", "gst_percent",
                                   "loyalty_enabled", "loyalty_points_per_100"]),
    ("ordering", "QR & online ordering", ["qr_ordering_enabled", "qr_auto_accept", "online_ordering_enabled",
                                           "accept_cash_on_delivery", "delivery_fee", "delivery_radius_km", "min_order_amount"]),
    ("payments", "Online payments (your Razorpay)", ["accept_online_payment", "razorpay_key_id", "razorpay_key_secret"]),
]


class RestaurantSettingsForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = [f for _, _, fields in SETTINGS_SECTIONS for f in fields]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "razorpay_key_secret": forms.PasswordInput(render_value=True),
        }
        help_texts = {
            "charge_gst": "Switch on once you are GST registered. Bills then show GST.",
            "qr_auto_accept": "QR orders go straight to the kitchen without staff accepting them.",
            "razorpay_key_id": "Guest payments go directly to your own Razorpay account.",
        }

    def sections(self):
        return [(key, title, [self[f] for f in fields]) for key, title, fields in SETTINGS_SECTIONS]


class SeoForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["seo_title", "seo_description", "tagline"]
        widgets = {"seo_description": forms.Textarea(attrs={"rows": 2})}
