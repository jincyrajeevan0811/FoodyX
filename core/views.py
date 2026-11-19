from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from restaurant.models import Restaurant
from saas.models import Plan, PlatformSettings
from saas.services import onboard_restaurant

from .forms import LoginForm, ProfileForm, SignupForm
from .modules import SINGLE_DEVICE_ROLES
from .permissions import home_url_for
from .utils import log_activity, send_platform_email

FEATURES = [
    ("zap", "Lightning-fast POS billing", "Bill a table in under 3 seconds with keyboard shortcuts, favourites and instant search."),
    ("layout-grid", "Live table floor", "Colour-coded tables show free, occupied, billed, reserved and cleaning at a glance."),
    ("chef-hat", "Kitchen display & KOT", "Orders route to the right station with timers that turn amber and red when food is late."),
    ("qr-code", "QR table ordering", "Guests scan, browse a beautiful menu, order and call a waiter from their phone."),
    ("globe", "Your own online store", "A commission-free ordering website for takeaway and delivery, with Razorpay payments."),
    ("bike", "Delivery & riders", "Assign riders, share an OTP, collect cash on delivery and track every drop."),
    ("split", "Split & multi-pay bills", "Part cash, part UPI, part card — settled in one tap, with change worked out for you."),
    ("bar-chart-3", "Reports that make sense", "Daily item sales, payment split, peak hours and best sellers, exportable to Excel."),
    ("sparkles", "Smart insights", "Plain-English tips: what to promote, what to drop, when to add staff, what to reorder."),
    ("package", "Inventory & stock", "Track stock, purchases and wastage with low-stock alerts before you run out."),
    ("heart-handshake", "Loyalty & customers", "Know your regulars, reward visits with points and run coupons that bring them back."),
    ("shield-check", "Roles & permissions", "Owner, manager, captain, cashier, kitchen, rider and store keeper — each sees only their job."),
]

STEPS = [
    ("Create your account", "Sign up in a minute — no card needed. Your 14-day trial starts straight away."),
    ("Add your menu & tables", "Type items or paste a list. Tables and QR codes are ready to print."),
    ("Start serving", "Take orders, send KOTs, print bills and watch the reports fill up."),
]

FAQS = [
    ("Do I need special hardware?", "No. FoodyX runs in any modern browser on a laptop, tablet or phone and prints to the thermal printer you already have."),
    ("Is there commission on online or QR orders?", "Never. Orders from your QR menu and online store are yours, and online payments go straight to your own Razorpay account."),
    ("Can every staff member have their own login?", "Yes. Each person gets a role — captain, cashier, kitchen, rider and more — and only sees what their job needs."),
    ("Can I switch plans later?", "Any time. Upgrade or downgrade from Plan & Billing and the change applies immediately."),
    ("Is my data safe?", "Your data is isolated per restaurant, protected by role-based access and every important action is written to an activity log."),
    ("Does it work for hotels with room service?", "Yes. Add rooms as an area, take room orders from the POS and post them to the guest's bill."),
]


def landing(request):
    plans = Plan.objects.filter(is_active=True, is_public=True)
    demo = Restaurant.objects.filter(is_active=True, online_ordering_enabled=True).order_by("created_at").first()
    return render(request, "public/landing.html", {
        "plans": plans,
        "features": FEATURES,
        "steps": STEPS,
        "faqs": FAQS,
        "demo_restaurant": demo,
    })


def legal(request, page):
    titles = {"terms": "Terms of service", "privacy": "Privacy policy"}
    if page not in titles:
        return redirect("core:landing")
    return render(request, "public/legal.html", {"page": page, "title": titles[page]})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:home_redirect")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.user
        login(request, user)
        if user.role in SINGLE_DEVICE_ROLES:
            user.current_session_key = request.session.session_key or ""
            user.save(update_fields=["current_session_key"])
        log_activity(request, "Signed in")
        nxt = request.POST.get("next") or request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            return redirect(nxt)
        return redirect("core:home_redirect")
    return render(request, "public/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("core:login")


def signup(request):
    ps = PlatformSettings.load()
    if not ps.allow_self_signup:
        messages.info(request, "New sign-ups are by invitation. Please contact our team.")
        return redirect("core:landing")
    if request.user.is_authenticated:
        return redirect("core:home_redirect")
    initial = {"plan": request.GET.get("plan", "")}
    form = SignupForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        plan = Plan.objects.filter(slug=d.get("plan"), is_active=True).first()
        try:
            restaurant, owner = onboard_restaurant(
                name=d["restaurant_name"], owner_name=d["owner_name"], phone=d["phone"], email=d["email"],
                password=d["password"], plan=plan, business_type=d["business_type"], city=d.get("city", ""),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "public/signup.html", {"form": form})
        login(request, owner)
        log_activity(request, "Restaurant signed up", f"{restaurant.name} on {restaurant.plan} trial", restaurant=restaurant)
        send_platform_email(
            f"Welcome to {ps.site_name}",
            f"Hi {owner.display_name},\n\nYour restaurant {restaurant.name} is ready. "
            f"Your free trial runs for {restaurant.subscription.days_left} days.\n\nHappy serving!\n{ps.site_name}",
            owner.email,
        )
        messages.success(request, f"Welcome to {ps.site_name}! Your free trial has started.")
        return redirect("restaurant:dashboard")
    return render(request, "public/signup.html", {"form": form})


@login_required
def home_redirect(request):
    return redirect(home_url_for(request.user))


@login_required
def profile(request):
    """Every user can change their own name, contact details and password."""
    user = request.user
    action = request.POST.get("action") if request.method == "POST" else None
    form = ProfileForm(request.POST if action == "profile" else None, instance=user, prefix="p")
    pw_form = PasswordChangeForm(user, request.POST if action == "password" else None, prefix="pw")
    if action == "profile" and form.is_valid():
        form.save()
        log_activity(request, "Profile updated", user.display_name)
        messages.success(request, "Your details were saved.")
        return redirect("core:profile")
    if action == "password" and pw_form.is_valid():
        pw_form.save()
        update_session_auth_hash(request, pw_form.user)
        log_activity(request, "Password changed", user.display_name)
        messages.success(request, "Your password was changed.")
        return redirect("core:profile")
    layout = "layouts/platform.html" if (user.is_platform and not user.restaurant_id) else "layouts/app.html"
    return render(request, "account/profile.html", {"form": form, "pw_form": pw_form, "layout": layout})
