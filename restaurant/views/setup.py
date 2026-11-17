"""Staff & roles, hardware, settings and plan & billing."""
from decimal import Decimal

from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.modules import ROLE_DESCRIPTIONS
from core.permissions import restaurant_required
from core.razorpay import RazorpayError, create_order, to_paise, verify_payment_signature
from core.utils import log_activity
from saas.models import Plan, PlatformPayment, PlatformSettings

from ..forms import DeviceForm, RestaurantSettingsForm, StaffForm
from ..models import Device

User = get_user_model()


# ----------------------------------------------------------------- staff
@restaurant_required("staff")
def staff(request):
    r = request.restaurant
    members = User.objects.filter(restaurant=r).order_by("-is_active", "role", "first_name")
    plan = r.plan
    return render(request, "restaurant/staff.html", {
        "members": members,
        "limit": plan.max_staff if plan else 0,
        "active_count": members.filter(is_active=True).count(),
        "role_desc": ROLE_DESCRIPTIONS,
    })


@restaurant_required("staff")
def staff_edit(request, pk=None):
    r = request.restaurant
    member = get_object_or_404(User, pk=pk, restaurant=r) if pk else None
    plan = r.plan
    if member is None and plan and plan.max_staff and User.objects.filter(restaurant=r, is_active=True).count() >= plan.max_staff:
        messages.error(request, f"Your plan allows {plan.max_staff} active logins. Upgrade or switch someone off first.")
        return redirect("restaurant:staff")
    if member and member.role == "owner" and request.user.role != "owner":
        messages.error(request, "Only the owner can edit the owner's login.")
        return redirect("restaurant:staff")
    form = StaffForm(request.POST or None, instance=member, restaurant=r)
    if request.method == "POST" and form.is_valid():
        if member and member.pk == request.user.pk and not form.cleaned_data.get("is_active", True):
            messages.error(request, "You cannot switch off your own login.")
        else:
            user = form.save()
            log_activity(request, "Staff saved", f"{user.display_name} ({user.role_label})")
            messages.success(request, f"{user.display_name} saved. They sign in with {user.phone}.")
            return redirect("restaurant:staff")
    return render(request, "restaurant/staff_form.html", {"form": form, "member": member, "role_desc": ROLE_DESCRIPTIONS})


@restaurant_required("staff")
@require_POST
def staff_toggle(request, pk):
    member = get_object_or_404(User, pk=pk, restaurant=request.restaurant)
    if member.pk == request.user.pk or member.role == "owner":
        messages.error(request, "This login cannot be switched off here.")
    else:
        member.is_active = not member.is_active
        member.save(update_fields=["is_active"])
        log_activity(request, "Staff login " + ("on" if member.is_active else "off"), member.display_name)
        messages.success(request, f"{member.display_name} is now {'active' if member.is_active else 'switched off'}.")
    return redirect("restaurant:staff")


@restaurant_required("staff")
def staff_permissions(request):
    from saas.views import _permissions_matrix

    if request.user.role not in ("owner", "admin"):
        messages.error(request, "Only the owner or admin can change role permissions.")
        return redirect("restaurant:staff")
    return _permissions_matrix(request, request.restaurant, "restaurant/staff_permissions.html",
                               redirect_to=("restaurant:staff_permissions", {}))


# -------------------------------------------------------------- hardware
@restaurant_required("hardware")
def hardware(request):
    r = request.restaurant
    return render(request, "restaurant/hardware.html", {
        "devices": Device.objects.filter(restaurant=r), "kinds": Device.KINDS,
        "limit": r.plan.max_devices if r.plan else 0,
    })


@restaurant_required("hardware")
def device_edit(request, pk=None):
    r = request.restaurant
    device = get_object_or_404(Device, pk=pk, restaurant=r) if pk else None
    plan = r.plan
    if device is None and plan and plan.max_devices and r.devices.count() >= plan.max_devices:
        messages.error(request, f"Your plan allows {plan.max_devices} devices.")
        return redirect("restaurant:hardware")
    form = DeviceForm(request.POST or None, instance=device, initial={"kind": request.GET.get("kind")})
    if request.method == "POST":
        if request.POST.get("delete") and device:
            device.delete()
            messages.success(request, "Device removed.")
            return redirect("restaurant:hardware")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = r
            obj.save()
            messages.success(request, f"{obj.name} saved.")
            return redirect("restaurant:hardware")
    return render(request, "restaurant/device_form.html", {"form": form, "device": device})


@restaurant_required("hardware")
def device_test(request, pk):
    device = get_object_or_404(Device, pk=pk, restaurant=request.restaurant)
    return render(request, "restaurant/print_test.html", {"device": device})


# -------------------------------------------------------------- settings
@restaurant_required("settings")
def settings_view(request):
    r = request.restaurant
    form = RestaurantSettingsForm(request.POST or None, instance=r)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_activity(request, "Restaurant settings updated")
        messages.success(request, "Settings saved.")
        return redirect(f"{request.path}#{request.POST.get('section', 'profile')}")
    return render(request, "restaurant/settings.html", {"form": form})


# ---------------------------------------------------------- plan & billing
def _price(plan, cycle):
    ps = PlatformSettings.load()
    amount = plan.price_for(cycle)
    gst = (amount * ps.gst_percent / 100).quantize(Decimal("0.01"))
    return amount, gst, amount + gst


@restaurant_required("billing")
def billing(request):
    r = request.restaurant
    plans = Plan.objects.filter(is_active=True)
    return render(request, "restaurant/billing.html", {
        "sub": getattr(r, "subscription", None),
        "plans": plans,
        "payments": PlatformPayment.objects.filter(restaurant=r).select_related("plan")[:20],
        "can_pay": request.user.role in ("owner", "admin"),
        "gst_percent": PlatformSettings.load().gst_percent,
    })


@restaurant_required("billing")
@require_POST
def billing_checkout(request):
    r = request.restaurant
    if request.user.role not in ("owner", "admin"):
        messages.error(request, "Only the owner can change the plan.")
        return redirect("restaurant:billing")
    plan = get_object_or_404(Plan, pk=request.POST.get("plan"), is_active=True)
    cycle = "yearly" if request.POST.get("cycle") == "yearly" else "monthly"
    if plan.is_custom_pricing:
        messages.info(request, "Our team will contact you about this plan.")
        log_activity(request, "Enterprise plan enquiry", plan.name)
        return redirect("restaurant:billing")
    amount, gst, total = _price(plan, cycle)
    ps = PlatformSettings.load()
    pay = PlatformPayment.objects.create(
        restaurant=r, plan=plan, billing_cycle=cycle, amount=amount, gst_amount=gst, total=total,
        method="razorpay", recorded_by=request.user,
    )
    ctx = {"pay": pay, "plan": plan, "cycle": cycle, "ps": ps, "simulate": False}
    if total <= 0:
        pay.mark_paid(method="other")
        messages.success(request, f"You are now on the {plan.name} plan.")
        return redirect("restaurant:billing")
    if ps.razorpay_ready:
        try:
            rp = create_order(ps.razorpay_key_id, ps.razorpay_key_secret, to_paise(total), f"sub-{pay.pk}",
                              {"restaurant": r.name, "plan": plan.name, "cycle": cycle})
        except RazorpayError as exc:
            pay.status = "failed"
            pay.save(update_fields=["status"])
            messages.error(request, f"Payment could not start: {exc}")
            return redirect("restaurant:billing")
        pay.razorpay_order_id = rp["id"]
        pay.save(update_fields=["razorpay_order_id"])
        ctx["rp_order"] = rp
        ctx["amount_paise"] = to_paise(total)
    elif dj_settings.DEBUG:
        ctx["simulate"] = True
    else:
        pay.delete()
        messages.error(request, "Online payments are not set up yet. Please contact support to upgrade.")
        return redirect("restaurant:billing")
    return render(request, "restaurant/billing_checkout.html", ctx)


@restaurant_required("billing")
@require_POST
def billing_verify(request, pk):
    pay = get_object_or_404(PlatformPayment, pk=pk, restaurant=request.restaurant)
    ps = PlatformSettings.load()
    if request.POST.get("simulate") and dj_settings.DEBUG and not ps.razorpay_ready:
        pay.mark_paid(payment_id="sim_" + str(pay.pk))
        messages.success(request, f"Test payment done — you are on the {pay.plan.name} plan.")
        return redirect("restaurant:billing")
    ok = verify_payment_signature(
        request.POST.get("razorpay_order_id"), request.POST.get("razorpay_payment_id"),
        request.POST.get("razorpay_signature"), ps.razorpay_key_secret,
    )
    if ok and request.POST.get("razorpay_order_id") == pay.razorpay_order_id:
        pay.mark_paid(payment_id=request.POST.get("razorpay_payment_id", ""))
        log_activity(request, "Subscription paid", f"{pay.plan} · ₹{pay.total}")
        messages.success(request, f"Payment received — thank you! You are on the {pay.plan.name} plan.")
    else:
        pay.status = "failed"
        pay.save(update_fields=["status"])
        messages.error(request, "We could not verify the payment. If money was deducted it will be confirmed automatically.")
    return redirect("restaurant:billing")


@restaurant_required("billing")
def billing_invoice(request, pk):
    pay = get_object_or_404(PlatformPayment, pk=pk, restaurant=request.restaurant, status="paid")
    return render(request, "platform/invoice.html", {"pay": pay, "ps": PlatformSettings.load()})
