from django import forms
from django.contrib.auth import authenticate, get_user_model

User = get_user_model()


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Mobile number, email or username",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "placeholder": "98xxxxxx10 or you@restaurant.com"}),
    )
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "••••••••"}))

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get("username") and data.get("password"):
            self.user = authenticate(self.request, username=data["username"], password=data["password"])
            if self.user is None:
                raise forms.ValidationError("That login and password don't match. Please try again.")
        return data


class SignupForm(forms.Form):
    restaurant_name = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"placeholder": "e.g. FoodyX Kitchen"}))
    business_type = forms.ChoiceField(choices=[])
    city = forms.CharField(max_length=60, required=False)
    owner_name = forms.CharField(max_length=120, label="Your name")
    phone = forms.CharField(max_length=15, label="Mobile number")
    email = forms.EmailField()
    password = forms.CharField(min_length=6, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    plan = forms.ChoiceField(choices=[], required=False)
    agree = forms.BooleanField(label="I agree to the Terms and Privacy policy")

    def __init__(self, *args, **kwargs):
        from restaurant.models import Restaurant
        from saas.models import Plan

        super().__init__(*args, **kwargs)
        self.fields["business_type"].choices = Restaurant.BUSINESS_TYPES
        self.fields["plan"].choices = [
            (p.slug, p.name) for p in Plan.objects.filter(is_active=True, is_public=True, is_custom_pricing=False)
        ]

    def clean_phone(self):
        phone = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit() or ch == "+")
        if len(phone) < 10:
            raise forms.ValidationError("Enter a valid mobile number.")
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError("This mobile number already has a FoodyX login.")
        return phone

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email already has a FoodyX login.")
        return email
