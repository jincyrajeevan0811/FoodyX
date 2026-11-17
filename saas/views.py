import json
import platform as py_platform
import secrets
from datetime import timedelta
from decimal import Decimal

import django
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.modules import (
    ALL_MODULES, DEFAULT_ROLE_MODULES, MODULES, PLAN_FEATURE_CODES, PLATFORM_ROLES,
    RESTAURANT_ROLE_CHOICES, ROLE_CHOICES, ROLE_DESCRIPTIONS,
)
from core.permissions import platform_required
from core.razorpay import verify_webhook_signature
from core.utils import log_activity, send_platform_email
from restaurant.models import Order, Restaurant, RolePermission

from .forms import (
    ManualPaymentForm, OnboardRestaurantForm, PlanForm, PlatformSettingsForm,
    RestaurantEditForm, SubscriptionForm, TeamMemberForm,
)
from .models import ActivityLog, Plan, PlatformPayment, PlatformSettings, Subscription
from .services import onboard_restaurant

User = get_user_model()


def _gst(amount):
    ps = PlatformSettings.load()
    return (Decimal(amount) * ps.gst_percent / 100).quantize(Decimal("0.01"))


# ------------------------------------------------------------- overview
@platform_required()
def overview(request):
    now = timezone.now()
    today = timezone.localdate()
    month_start = today.replace(day=1)
    subs = Subscription.objects.select_related("plan", "restaurant")
    live_subs = [s for s in subs if s.is_live]

    restaurants_total = Restaurant.objects.count()
    on_trial = sum(1 for s in live_subs if s.status == "trial")
    expired = sum(1 for s in subs if s.effective_status == "expired")
    paying = [s for s in live_subs if s.status == "active"]
    mrr = sum((s.monthly_value for s in paying), Decimal("0"))

    paid = PlatformPayment.objects.filter(status="paid")
    collected_month = paid.filter(paid_at__date__gte=month_start).aggregate(s=Sum("total"))["s"] or 0
    collected_all = paid.aggregate(s=Sum("total"))["s"] or 0

    expiring = [
        s for s in subs.order_by("current_period_end")
        if s.status in ("trial", "active") and now <= s.current_period_end <= now + timedelta(days=7)
    ]

    todays_orders = Order.objects.filter(created_at__date=today)
    completed_today = todays_orders.filter(status="completed").aggregate(s=Sum("total"))["s"] or 0

    # Revenue trend for the last 6 months
    six_months = (month_start - timedelta(days=160)).replace(day=1)
    by_month = (
        paid.filter(paid_at__date__gte=six_months)
        .annotate(m=TruncMonth("paid_at")).values("m").annotate(total=Sum("total")).order_by("m")
    )
    trend_map = {row["m"].strftime("%b %Y"): float(row["total"]) for row in by_month if row["m"]}
    labels, values = [], []
    cursor = six_months
    for _ in range(6):
        key = cursor.strftime("%b %Y")
        labels.append(cursor.strftime("%b"))
        values.append(trend_map.get(key, 0))
        cursor = (cursor + timedelta(days=32)).replace(day=1)

    plan_mix = (
        Subscription.objects.values("plan__name").annotate(n=Count("id")).order_by("-n")
    )

    ps = PlatformSettings.load()
    checklist = ps.checklist()
    return render(request, "platform/overview.html", {
        "restaurants_total": restaurants_total,
        "on_trial": on_trial,
        "expired": expired,
        "paying_count": len(paying),
        "mrr": mrr,
        "collected_month": collected_month,
        "collected_all": collected_all,
        "checklist": checklist,
        "checklist_done": sum(1 for c in checklist if c[1]),
        "checklist_left": sum(1 for c in checklist if not c[1]),
        "expiring": expiring,
        "orders_today": todays_orders.count(),
        "sales_today": completed_today,
        "recent_restaurants": Restaurant.objects.select_related("subscription__plan").order_by("-created_at")[:6],
        "recent_activity": ActivityLog.objects.select_related("actor", "restaurant")[:8],
        "trend_labels": json.dumps(labels),
        "trend_values": json.dumps(values),
        "plan_mix": plan_mix,
    })


# ---------------------------------------------------------- restaurants
@platform_required()
def restaurants(request):
    qs = Restaurant.objects.select_related("subscription__plan").annotate(staff_count=Count("staff", distinct=True))
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    rows = list(qs.order_by("-created_at"))
    if status == "paused":
        rows = [r for r in rows if not (r.is_active and r.access_granted)]
    elif status:
        rows = [r for r in rows if getattr(r, "subscription", None) and r.subscription.effective_status == status]
    counts = {"all": Restaurant.objects.count()}
    return render(request, "platform/restaurants.html", {
        "rows": rows, "q": q, "status": status, "counts": counts,
        "status_tabs": [("", "All"), ("trial", "On trial"), ("active", "Paying"), ("expired", "Expired"), ("paused", "Paused")],
    })


@platform_required("manage")
def restaurant_add(request):
    ps = PlatformSettings.load()
    form = OnboardRestaurantForm(request.POST or None, initial={"trial_days": ps.default_trial_days})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        restaurant, owner = onboard_restaurant(
            name=d["name"], owner_name=d["owner_name"], phone=d["phone"], email=d["email"],
            password=d["password"], plan=d["plan"], status=d["start_as"], cycle=d["billing_cycle"],
            trial_days=d["trial_days"], business_type=d["business_type"], city=d.get("city", ""),
            access_granted=d.get("access_granted", False),
        )
        log_activity(request, "Restaurant onboarded", f"{restaurant.name} on {d['plan'].name} ({d['start_as']})", restaurant=restaurant)
        if d.get("send_welcome"):
            site = ps.site_url or request.build_absolute_uri("/")
            send_platform_email(
                f"Your {ps.site_name} account is ready",
                f"Hi {owner.display_name},\n\n{restaurant.name} is now set up on {ps.site_name} "
                f"({d['plan'].name} plan).\n\nSign in at {site.rstrip('/')}/login/\n"
                f"Login: {owner.phone or owner.email}\nPassword: {d['password']}\n\n"
                "Please change your password after signing in.\n",
                owner.email,
            )
        messages.success(request, f"{restaurant.name} is onboarded. The owner can sign in with {owner.phone}.")
        return redirect("saas:restaurant_detail", pk=restaurant.pk)
    return render(request, "platform/restaurant_add.html", {"form": form})


@platform_required()
def restaurant_detail(request, pk):
    restaurant = get_object_or_404(Restaurant.objects.select_related("subscription__plan"), pk=pk)
    sub = getattr(restaurant, "subscription", None)
    if sub is None:
        plan = Plan.objects.filter(is_active=True).first()
        if plan:
            sub = Subscription(restaurant=restaurant, plan=plan, current_period_end=timezone.now())
            sub.start_trial()
            sub.save()
    sub_form = SubscriptionForm(instance=sub, prefix="sub") if sub else None
    edit_form = RestaurantEditForm(instance=restaurant, prefix="info")
    today = timezone.localdate()
    orders = Order.objects.filter(restaurant=restaurant)
    stats = {
        "orders_total": orders.count(),
        "orders_today": orders.filter(created_at__date=today).count(),
        "sales_30": orders.filter(status="completed", created_at__date__gte=today - timedelta(days=30)).aggregate(s=Sum("total"))["s"] or 0,
        "menu_items": restaurant.menu_items.count(),
        "tables": restaurant.tables.count(),
    }
    return render(request, "platform/restaurant_detail.html", {
        "r": restaurant,
        "sub": sub,
        "sub_form": sub_form,
        "edit_form": edit_form,
        "staff": restaurant.staff.order_by("role", "first_name"),
        "payments": restaurant.platform_payments.select_related("plan")[:20],
        "activity": restaurant.activities.select_related("actor")[:15],
        "stats": stats,
    })


@platform_required("manage")
@require_POST
def restaurant_action(request, pk):
    restaurant = get_object_or_404(Restaurant, pk=pk)
    action = request.POST.get("action")
    sub = getattr(restaurant, "subscription", None)

    if action == "update_info":
        form = RestaurantEditForm(request.POST, instance=restaurant, prefix="info")
        if form.is_valid():
            form.save()
            log_activity(request, "Restaurant details updated", restaurant.name, restaurant=restaurant)
            messages.success(request, "Restaurant details saved.")
        else:
            messages.error(request, "Please fix the highlighted details: " + "; ".join(
                f"{k}: {v[0]}" for k, v in form.errors.items()))
    elif action == "update_subscription" and sub:
        form = SubscriptionForm(request.POST, instance=sub, prefix="sub")
        if form.is_valid():
            form.save()
            log_activity(request, "Subscription changed", f"{sub.plan.name} · {sub.get_status_display()} until {sub.current_period_end:%d %b %Y}", restaurant=restaurant)
            messages.success(request, "Subscription updated.")
        else:
            messages.error(request, "Could not update the subscription: " + "; ".join(
                f"{k}: {v[0]}" for k, v in form.errors.items()))
    elif action == "extend" and sub:
        days = int(request.POST.get("days") or 7)
        base = max(sub.current_period_end, timezone.now())
        sub.current_period_end = base + timedelta(days=days)
        if sub.status in ("expired", "cancelled", "past_due"):
            sub.status = "trial" if sub.status != "past_due" else "active"
        sub.save()
        log_activity(request, "Subscription extended", f"+{days} days", restaurant=restaurant)
        messages.success(request, f"Extended by {days} days.")
    elif action == "toggle_access":
        restaurant.access_granted = not restaurant.access_granted
        restaurant.save(update_fields=["access_granted"])
        state = "granted" if restaurant.access_granted else "paused"
        log_activity(request, f"Access {state}", restaurant.name, restaurant=restaurant)
        messages.success(request, f"Access {state} for {restaurant.name}.")
    elif action == "reset_owner_password":
        owner = restaurant.owner
        if owner:
            new_password = secrets.token_urlsafe(6)
            owner.set_password(new_password)
            owner.save()
            log_activity(request, "Owner password reset", owner.display_name, restaurant=restaurant)
            send_platform_email("Your password was reset", f"Your new password is: {new_password}", owner.email)
            messages.success(request, f"New password for {owner.display_name}: {new_password}  (share it securely).")
    elif action == "delete" and request.user.is_super_admin:
        name = restaurant.name
        if request.POST.get("confirm_name", "").strip() != name:
            messages.error(request, "Type the restaurant name exactly to delete it.")
        else:
            log_activity(request, "Restaurant deleted", name)
            restaurant.delete()
            messages.success(request, f"{name} and all its data were deleted.")
            return redirect("saas:restaurants")
    else:
        messages.error(request, "Unknown action.")
    return redirect("saas:restaurant_detail", pk=pk)


@platform_required("manage")
def restaurant_permissions(request, pk):
    restaurant = get_object_or_404(Restaurant, pk=pk)
    return _permissions_matrix(request, restaurant, "platform/restaurant_permissions.html",
                               redirect_to=("saas:restaurant_permissions", {"pk": pk}))


def _permissions_matrix(request, restaurant, template, redirect_to):
    """Shared by the Super Admin panel and the owner's Staff & Roles page."""
    from core.permissions import role_modules

    roles = [r for r in RESTAURANT_ROLE_CHOICES if r[0] != "owner"]
    if request.method == "POST":
        for role, _ in roles:
            selected = [m for m in request.POST.getlist(f"perm_{role}") if m in ALL_MODULES]
            RolePermission.objects.update_or_create(
                restaurant=restaurant, role=role, defaults={"modules": selected}
            )
        if request.POST.get("reset"):
            RolePermission.objects.filter(restaurant=restaurant).delete()
            messages.success(request, "Permissions reset to the FoodyX defaults.")
        else:
            messages.success(request, "Role permissions saved.")
        log_activity(request, "Role permissions updated", restaurant.name, restaurant=restaurant)
        name, kwargs = redirect_to
        return redirect(name, **kwargs)
    matrix = []
    for role, label in roles:
        current = role_modules(restaurant, role)
        matrix.append({"role": role, "label": label, "desc": ROLE_DESCRIPTIONS.get(role, ""), "modules": current})
    modules = [
        {"code": m[0], "label": m[1], "icon": m[2], "group": m[3],
         "locked": m[0] in PLAN_FEATURE_CODES and not restaurant.has_feature(m[0])}
        for m in MODULES
    ]
    return render(request, template, {"r": restaurant, "matrix": matrix, "modules": modules})


# ----------------------------------------------------------------- plans
@platform_required()
def plans(request):
    plan_list = Plan.objects.annotate(sub_count=Count("subscriptions"))
    return render(request, "platform/plans.html", {"plans": plan_list})


@platform_required("manage")
def plan_edit(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        if plan.is_popular:
            Plan.objects.exclude(pk=plan.pk).update(is_popular=False)
        log_activity(request, "Plan saved", plan.name)
        messages.success(request, f"Plan “{plan.name}” saved.")
        return redirect("saas:plans")
    return render(request, "platform/plan_form.html", {"form": form, "plan": plan})


@platform_required("manage")
@require_POST
def plan_delete(request, pk):
    plan = get_object_or_404(Plan, pk=pk)
    if plan.subscriptions.exists():
        plan.is_active = False
        plan.save(update_fields=["is_active"])
        messages.info(request, f"“{plan.name}” has subscribers, so it was deactivated instead of deleted.")
    else:
        plan.delete()
        messages.success(request, "Plan deleted.")
    log_activity(request, "Plan removed", plan.name)
    return redirect("saas:plans")


# -------------------------------------------------------------- payments
@platform_required()
def payments(request):
    qs = PlatformPayment.objects.select_related("restaurant", "plan", "recorded_by")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(restaurant__name__icontains=q) | Q(invoice_no__icontains=q) | Q(razorpay_payment_id__icontains=q))
    paid = PlatformPayment.objects.filter(status="paid")
    month_start = timezone.localdate().replace(day=1)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "platform/payments.html", {
        "page": page, "status": status, "q": q,
        "total_all": paid.aggregate(s=Sum("total"))["s"] or 0,
        "total_month": paid.filter(paid_at__date__gte=month_start).aggregate(s=Sum("total"))["s"] or 0,
        "gst_month": paid.filter(paid_at__date__gte=month_start).aggregate(s=Sum("gst_amount"))["s"] or 0,
        "failed_count": PlatformPayment.objects.filter(status="failed").count(),
    })


@platform_required("manage")
def payment_add(request):
    initial = {}
    if request.GET.get("restaurant"):
        r = Restaurant.objects.filter(pk=request.GET["restaurant"]).first()
        if r and r.plan:
            initial = {"restaurant": r, "plan": r.plan, "amount": r.plan.price_monthly}
    form = ManualPaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        pay = form.save(commit=False)
        pay.gst_amount = _gst(pay.amount)
        pay.total = pay.amount + pay.gst_amount
        pay.recorded_by = request.user
        pay.save()
        if form.cleaned_data.get("activate_subscription"):
            pay.mark_paid(method=pay.method)
        log_activity(request, "Payment recorded", f"₹{pay.total} via {pay.get_method_display()}", restaurant=pay.restaurant)
        messages.success(request, "Payment recorded.")
        return redirect("saas:payments")
    return render(request, "platform/payment_form.html", {"form": form})


@platform_required()
def invoice(request, pk):
    pay = get_object_or_404(PlatformPayment.objects.select_related("restaurant", "plan"), pk=pk)
    return render(request, "platform/invoice.html", {"pay": pay, "ps": PlatformSettings.load()})


# ----------------------------------------------------------------- users
@platform_required()
def users(request):
    qs = User.objects.select_related("restaurant")
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(phone__icontains=q) | Q(email__icontains=q) | Q(restaurant__name__icontains=q))
    if role:
        qs = qs.filter(role=role)
    page = Paginator(qs.order_by("-date_joined"), 30).get_page(request.GET.get("page"))
    return render(request, "platform/users.html", {"page": page, "q": q, "role": role, "roles": ROLE_CHOICES})


@platform_required("manage")
@require_POST
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot switch off your own login.")
    elif user.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only a superuser can change another superuser.")
    else:
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        log_activity(request, "Login " + ("enabled" if user.is_active else "disabled"), user.display_name, restaurant=user.restaurant)
        messages.success(request, f"{user.display_name} is now {'active' if user.is_active else 'disabled'}.")
    return redirect(request.POST.get("next") or "saas:users")


# ------------------------------------------------------------ team/roles
@platform_required()
def team(request):
    members = User.objects.filter(Q(role__in=PLATFORM_ROLES) | Q(is_superuser=True), restaurant__isnull=True)
    return render(request, "platform/team.html", {
        "members": members,
        "role_info": [
            ("Super admin", "Everything, including platform settings, team management and deleting restaurants."),
            ("Platform admin", "Onboard restaurants, manage plans, payments, access and permissions."),
            ("Platform support", "Read-only view of restaurants, users, payments and activity to help customers."),
        ],
    })


@platform_required("team")
def team_edit(request, pk=None):
    member = get_object_or_404(User, pk=pk, restaurant__isnull=True) if pk else None
    form = TeamMemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_activity(request, "Team member saved", f"{user.display_name} ({user.role_label})")
        messages.success(request, f"{user.display_name} saved.")
        return redirect("saas:team")
    return render(request, "platform/team_form.html", {"form": form, "member": member})


# --------------------------------------------------------- activity log
@platform_required()
def activity(request):
    qs = ActivityLog.objects.select_related("actor", "restaurant")
    q = request.GET.get("q", "").strip()
    scope = request.GET.get("scope", "")
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(detail__icontains=q) | Q(actor__username__icontains=q)
                       | Q(restaurant__name__icontains=q))
    if scope == "platform":
        qs = qs.filter(restaurant__isnull=True)
    elif scope == "restaurants":
        qs = qs.filter(restaurant__isnull=False)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "platform/activity.html", {"page": page, "q": q, "scope": scope})


# --------------------------------------------------------------- settings
@platform_required("settings")
def settings_view(request):
    ps = PlatformSettings.load()
    form = PlatformSettingsForm(request.POST or None, instance=ps)
    if request.method == "POST":
        if request.POST.get("action") == "test_email":
            ok = send_platform_email(f"{ps.site_name} test email", "SMTP is working.", request.user.email)
            if ok:
                messages.success(request, f"Test email sent to {request.user.email or 'your address'}.")
            else:
                messages.error(request, "Sending failed. Check the SMTP details.")
            return redirect("saas:settings")
        if form.is_valid():
            form.save()
            log_activity(request, "Platform settings updated")
            messages.success(request, "Platform settings saved.")
            return redirect(f"{request.path}#{request.POST.get('section', 'general')}")
    webhook_url = request.build_absolute_uri("/webhooks/razorpay/")
    return render(request, "platform/settings.html", {"form": form, "webhook_url": webhook_url, "ps": ps})


# ------------------------------------------------------------- health
@platform_required()
def health(request):
    checks = []
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks.append(("Database", True, connection.vendor))
    except Exception as exc:  # pragma: no cover
        checks.append(("Database", False, str(exc)))
    ps = PlatformSettings.load()
    checks.append(("Razorpay keys", ps.razorpay_ready, "Configured" if ps.razorpay_ready else "Add keys in Platform settings"))
    checks.append(("Razorpay webhook", bool(ps.razorpay_webhook_secret), "Secret saved" if ps.razorpay_webhook_secret else "Not set"))
    checks.append(("Email (SMTP)", ps.smtp_ready, ps.smtp_host or "Using console email backend"))
    from django.conf import settings as dj

    checks.append(("Debug mode off", not dj.DEBUG, "DEBUG is on — switch it off in production" if dj.DEBUG else "Production mode"))
    checks.append(("Secret key changed", "dev-only" not in dj.SECRET_KEY, "Set FOODYX_SECRET_KEY" if "dev-only" in dj.SECRET_KEY else "Custom key in use"))
    counts = [
        ("Restaurants", Restaurant.objects.count()),
        ("Users", User.objects.count()),
        ("Orders", Order.objects.count()),
        ("Plans", Plan.objects.count()),
        ("Payments", PlatformPayment.objects.count()),
        ("Activity entries", ActivityLog.objects.count()),
    ]
    env = [
        ("Python", py_platform.python_version()),
        ("Django", django.get_version()),
        ("Server time", timezone.localtime().strftime("%d %b %Y, %I:%M %p")),
        ("Time zone", dj.TIME_ZONE),
    ]
    return render(request, "platform/health.html", {"checks": checks, "counts": counts, "env": env})


# --------------------------------------------------------- razorpay hook
@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """Receives Razorpay events (payment.captured / order.paid)."""
    ps = PlatformSettings.load()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(request.body, signature, ps.razorpay_webhook_secret):
        return HttpResponseBadRequest("invalid signature")
    try:
        event = json.loads(request.body.decode())
    except ValueError:
        return HttpResponseBadRequest("bad json")
    if event.get("event") in ("payment.captured", "order.paid"):
        entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = entity.get("order_id")
        payment_id = entity.get("id", "")
        if order_id:
            pay = PlatformPayment.objects.filter(razorpay_order_id=order_id).first()
            if pay and pay.mark_paid(payment_id=payment_id):
                log_activity(None, "Subscription paid (webhook)", f"₹{pay.total}", restaurant=pay.restaurant)
    elif event.get("event") == "payment.failed":
        entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        PlatformPayment.objects.filter(razorpay_order_id=entity.get("order_id"), status="created").update(status="failed")
    return HttpResponse("ok")
