"""Guest-facing pages: QR table menu, online store and order tracking."""
import json

from django.conf import settings as dj_settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.razorpay import RazorpayError, create_order, to_paise, verify_payment_signature
from restaurant.models import Coupon, Order, Restaurant, Table, WaiterCall
from restaurant.services import accept_order, get_or_create_customer, parse_cart, record_payments
from restaurant.views.common import menu_payload


def _restaurant_open(r):
    sub = getattr(r, "subscription", None)
    return r.is_active and r.access_granted and sub is not None and sub.is_live


def _offers(r):
    from django.db.models import Q
    from django.utils import timezone

    today = timezone.localdate()
    return list(
        Coupon.objects.filter(restaurant=r, is_active=True)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))[:6]
    )


def _bill_info(r, mode):
    return {
        "gst": float(r.gst_percent) if r.charge_gst else 0,
        "service": float(r.service_charge_percent) if mode == "table" else 0,
        "delivery_fee": float(r.delivery_fee),
        "min_order": float(r.min_order_amount),
    }


def _remember(request, order):
    ids = request.session.get("my_orders", [])
    ids = [str(order.public_id)] + [i for i in ids if i != str(order.public_id)]
    request.session["my_orders"] = ids[:10]


# ----------------------------------------------------------- QR ordering
def table_menu(request, token):
    table = get_object_or_404(Table.objects.select_related("restaurant", "area"), qr_token=token)
    r = table.restaurant
    if not (r.is_active and r.access_granted):
        raise Http404
    can_order = _restaurant_open(r) and r.qr_ordering_enabled and r.has_feature("qr_ordering")
    my_orders = Order.objects.filter(public_id__in=request.session.get("my_orders", []), table=table)
    return render(request, "storefront/menu.html", {
        "r": r, "table": table, "menu": menu_payload(r, online_only=False), "can_order": can_order,
        "mode": "table", "my_orders": my_orders[:3],
        "post_url": request.path + "order/",
        "offers": [], "bill": _bill_info(r, "table"),
    })


@require_POST
def table_order(request, token):
    table = get_object_or_404(Table.objects.select_related("restaurant", "area"), qr_token=token)
    r = table.restaurant
    if not (_restaurant_open(r) and r.qr_ordering_enabled and r.has_feature("qr_ordering")):
        messages.error(request, "Ordering from the table is not available right now. Please ask our staff.")
        return redirect("storefront:table_menu", token=token)
    try:
        cart = parse_cart(r, json.loads(request.POST.get("cart") or "[]"))
    except ValueError:
        cart = []
    if not cart:
        messages.error(request, "Your cart is empty.")
        return redirect("storefront:table_menu", token=token)
    name = request.POST.get("name", "").strip()[:120]
    phone = request.POST.get("phone", "").strip()[:15]
    order = Order(
        restaurant=r, table=table, source="qr",
        order_type="room" if table.area and table.area.kind == "room" else "dine_in",
        status="awaiting", customer_name=name, customer_phone=phone,
        note=request.POST.get("note", "").strip()[:255],
    )
    if phone:
        order.customer = get_or_create_customer(r, phone, name)
    order.save()
    from restaurant.models import OrderItem

    for line in cart:
        mi = line["menu_item"]
        OrderItem.objects.create(order=order, menu_item=mi, name=mi.name, price=mi.price, qty=line["qty"],
                                 note=line["note"], food_type=mi.food_type, station=mi.station, kot_status="pending")
    order.recalc()
    if r.qr_auto_accept:
        accept_order(order)
    _remember(request, order)
    return redirect("storefront:track", public_id=order.public_id)


@require_POST
def call_waiter(request, token):
    table = get_object_or_404(Table, qr_token=token)
    reason = request.POST.get("reason", "Call waiter")[:60]
    if not WaiterCall.objects.filter(table=table, resolved=False).exists():
        WaiterCall.objects.create(restaurant=table.restaurant, table=table, reason=reason)
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True})
    messages.success(request, "A waiter is on the way.")
    return redirect("storefront:table_menu", token=token)


# ---------------------------------------------------------- online store
def store(request, slug):
    r = get_object_or_404(Restaurant, slug=slug)
    if not (r.is_active and r.access_granted):
        raise Http404
    can_order = _restaurant_open(r) and r.online_ordering_enabled and r.has_feature("online_store")
    return render(request, "storefront/menu.html", {
        "r": r, "menu": menu_payload(r, online_only=True), "can_order": can_order, "mode": "store",
        "delivery_ok": r.has_feature("delivery"),
        "pay_online": r.online_payments_ready and r.has_feature("online_payments"),
        "post_url": request.path + "checkout/",
        "my_orders": Order.objects.filter(public_id__in=request.session.get("my_orders", []), restaurant=r)[:3],
        "offers": _offers(r) if r.has_feature("marketing") else [], "bill": _bill_info(r, "store"),
    })


@require_POST
def store_checkout(request, slug):
    r = get_object_or_404(Restaurant, slug=slug)
    if not (_restaurant_open(r) and r.online_ordering_enabled and r.has_feature("online_store")):
        messages.error(request, "Online ordering is closed right now.")
        return redirect("storefront:store", slug=slug)
    try:
        cart = parse_cart(r, json.loads(request.POST.get("cart") or "[]"))
    except ValueError:
        cart = []
    name = request.POST.get("name", "").strip()[:120]
    phone = request.POST.get("phone", "").strip()[:15]
    otype = "delivery" if request.POST.get("order_type") == "delivery" and r.has_feature("delivery") else "takeaway"
    address = request.POST.get("address", "").strip()
    pay_mode = request.POST.get("payment", "counter")
    errors = []
    if not cart:
        errors.append("Your cart is empty.")
    if not name or len("".join(c for c in phone if c.isdigit())) < 10:
        errors.append("Enter your name and a valid mobile number.")
    if otype == "delivery" and not address:
        errors.append("Enter the delivery address.")
    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect("storefront:store", slug=slug)

    from restaurant.models import OrderItem

    order = Order(
        restaurant=r, source="online", order_type=otype, status="awaiting", customer_name=name,
        customer_phone=phone, delivery_address=address, note=request.POST.get("note", "").strip()[:255],
    )
    order.customer = get_or_create_customer(r, phone, name, address)
    order.save()
    for line in cart:
        mi = line["menu_item"]
        OrderItem.objects.create(order=order, menu_item=mi, name=mi.name, price=mi.price, qty=line["qty"],
                                 note=line["note"], food_type=mi.food_type, station=mi.station, kot_status="pending")
    order.recalc(save=False)
    code = request.POST.get("coupon", "").strip().upper()
    if code:
        coupon = Coupon.objects.filter(restaurant=r, code=code).first()
        if coupon and coupon.is_valid_for(order.subtotal):
            order.discount = coupon.discount_for(order.subtotal)
            order.coupon_code = coupon.code
            coupon.times_used += 1
            coupon.save(update_fields=["times_used"])
    order.recalc()
    if r.min_order_amount and order.subtotal < r.min_order_amount:
        order.delete()
        messages.error(request, f"Minimum order is ₹{r.min_order_amount}.")
        return redirect("storefront:store", slug=slug)
    _remember(request, order)
    if pay_mode == "online" and r.online_payments_ready and r.has_feature("online_payments"):
        order.pay_online = True
        order.save(update_fields=["pay_online"])
        return redirect("storefront:pay", public_id=order.public_id)
    if otype == "delivery" and pay_mode == "cod" and not r.accept_cash_on_delivery:
        messages.info(request, "Cash on delivery isn't available — please pay online or at pickup.")
    return redirect("storefront:track", public_id=order.public_id)


# -------------------------------------------------------- guest payments
def pay(request, public_id):
    order = get_object_or_404(Order.objects.select_related("restaurant"), public_id=public_id)
    r = order.restaurant
    if order.payment_status == "paid":
        return redirect("storefront:track", public_id=public_id)
    if not (r.online_payments_ready and r.has_feature("online_payments")):
        messages.error(request, "Online payment is not available. Please pay at the counter.")
        return redirect("storefront:track", public_id=public_id)
    if not order.razorpay_order_id:
        try:
            rp = create_order(r.razorpay_key_id, r.razorpay_key_secret, to_paise(order.balance), f"ord-{order.pk}",
                              {"restaurant": r.name, "order": order.number})
        except RazorpayError as exc:
            messages.error(request, f"Payment could not start: {exc}")
            return redirect("storefront:track", public_id=public_id)
        order.razorpay_order_id = rp["id"]
        order.save(update_fields=["razorpay_order_id"])
    return render(request, "storefront/pay.html", {"order": order, "r": r, "amount_paise": to_paise(order.balance)})


@require_POST
def pay_verify(request, public_id):
    order = get_object_or_404(Order.objects.select_related("restaurant"), public_id=public_id)
    r = order.restaurant
    ok = verify_payment_signature(
        request.POST.get("razorpay_order_id"), request.POST.get("razorpay_payment_id"),
        request.POST.get("razorpay_signature"), r.razorpay_key_secret,
    )
    if ok and request.POST.get("razorpay_order_id") == order.razorpay_order_id and order.payment_status != "paid":
        record_payments(order, [("razorpay", order.balance, None, request.POST.get("razorpay_payment_id", ""))], None)
        # An online-paid order is still prepared normally: keep it open.
        if order.status == "completed" and order.order_type != "delivery":
            order.status = "awaiting" if not order.items.exclude(kot_status="pending").exists() else "accepted"
            order.completed_at = None
            order.save(update_fields=["status", "completed_at"])
        messages.success(request, "Payment successful. Thank you!")
    elif not ok:
        messages.error(request, "Payment could not be verified. If money was deducted, the restaurant will confirm it.")
    return redirect("storefront:track", public_id=public_id)


# ---------------------------------------------------------------- track
STEPS = [
    ("awaiting", "Order placed"),
    ("accepted", "Accepted"),
    ("preparing", "Being prepared"),
    ("ready", "Ready"),
    ("done", "Served / delivered"),
]


def track(request, public_id):
    order = get_object_or_404(Order.objects.select_related("restaurant", "table", "rider"), public_id=public_id)
    if order.merged_into_id:
        main = order.merged_into
    else:
        main = order
    status = main.status
    if status in ("served", "completed") or main.delivery_status == "delivered":
        idx = 4
    elif status == "out_for_delivery":
        idx = 4
    else:
        idx = {"awaiting": 0, "accepted": 1, "preparing": 2, "ready": 3}.get(status, 0)
    steps = [{"label": label, "done": i < idx, "current": i == idx} for i, (_, label) in enumerate(STEPS)]
    if main.order_type == "delivery":
        steps[4]["label"] = "Out for delivery" if status == "out_for_delivery" else "Delivered"
    r = order.restaurant
    return render(request, "storefront/track.html", {
        "order": order, "main": main, "r": r, "steps": steps,
        "items": order.items.all() if not order.merged_into_id else main.items.exclude(kot_status="cancelled"),
        "closed": status in ("cancelled", "rejected"),
        "can_pay_online": r.online_payments_ready and r.has_feature("online_payments") and main.payment_status != "paid"
                          and main.total > 0 and status not in ("cancelled", "rejected"),
        "debug": dj_settings.DEBUG,
    })
