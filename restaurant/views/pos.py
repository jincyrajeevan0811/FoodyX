import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.modules import CAN_CANCEL_ITEMS, CAN_DISCOUNT, CAN_OVERRIDE_TABLE_LOCK
from core.permissions import restaurant_required
from core.utils import log_activity

from ..models import Area, Coupon, Order, OrderItem, Payment, Table
from ..services import (
    add_items, find_recent_duplicates, get_or_create_customer, mark_billed, parse_cart,
    record_payments, release_table, sync_order_status_from_items,
)
from .common import get_order, menu_payload

LOCK_TIMEOUT = timedelta(hours=3)


def _dec(value):
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


@restaurant_required("pos")
def pos(request):
    r = request.restaurant
    open_orders = Order.objects.filter(restaurant=r, status__in=Order.OPEN_STATUSES)
    by_table = {}
    for o in open_orders.filter(table__isnull=False):
        by_table.setdefault(o.table_id, o)
    areas = []
    tables = list(Table.objects.filter(restaurant=r).select_related("area", "locked_by"))
    for area in Area.objects.filter(restaurant=r):
        area_tables = [t for t in tables if t.area_id == area.id]
        for t in area_tables:
            t.current = by_table.get(t.id)
        areas.append({"area": area, "tables": area_tables})
    loose = [t for t in tables if t.area_id is None]
    for t in loose:
        t.current = by_table.get(t.id)
    if loose:
        areas.append({"area": None, "tables": loose})
    counts = {s: sum(1 for t in tables if t.status == s) for s, _ in Table.STATUS_CHOICES}
    others = open_orders.filter(table__isnull=True).order_by("-created_at")
    return render(request, "restaurant/pos.html", {
        "areas": areas, "counts": counts, "other_orders": others, "status_choices": Table.STATUS_CHOICES,
    })


def _check_table_lock(request, table):
    """Returns (allowed, opened_as_owner)."""
    user = request.user
    locked = table.locked_by_id and table.locked_by_id != user.id
    stale = table.locked_at and timezone.now() - table.locked_at > LOCK_TIMEOUT
    if locked and not stale:
        if user.role in CAN_OVERRIDE_TABLE_LOCK:
            return True, True
        return False, False
    if user.role not in CAN_OVERRIDE_TABLE_LOCK or not table.locked_by_id or stale:
        table.locked_by = user
        table.locked_at = timezone.now()
        table.save(update_fields=["locked_by", "locked_at"])
    return True, False


def _order_screen(request, *, table=None, order=None, order_type="dine_in", opened_as_owner=False):
    r = request.restaurant
    role = request.user.role
    items = list(order.items.select_related("added_by").all()) if order else []
    kots = sorted({i.kot_no for i in items if i.kot_no})
    dup = request.session.pop("dup_cart", None)
    if dup and (not order or dup.get("order") != order.id):
        dup = None
    return render(request, "restaurant/pos_order.html", {
        "table": table,
        "order": order,
        "order_type": order.order_type if order else order_type,
        "items": items,
        "kots": kots,
        "menu": menu_payload(r),
        "can_cancel": role in CAN_CANCEL_ITEMS,
        "can_discount": role in CAN_DISCOUNT,
        "split_allowed": r.has_feature("split_billing"),
        "methods": [m for m in Payment.METHODS if m[0] != "razorpay"],
        "coupons": Coupon.objects.filter(restaurant=r, is_active=True),
        "opened_as_owner": opened_as_owner,
        "dup": dup,
        "last_kot": request.GET.get("kot"),
    })


@restaurant_required("pos")
def pos_table(request, pk):
    table = get_object_or_404(Table.objects.select_related("locked_by", "area"), pk=pk, restaurant=request.restaurant)
    allowed, as_owner = _check_table_lock(request, table)
    if not allowed:
        messages.error(request, f"Table {table.name} is being served by {table.locked_by.display_name} right now.")
        return redirect("restaurant:pos")
    if as_owner:
        messages.info(request, f"Opened as owner. {table.locked_by.display_name} keeps the table.")
    order = table.open_order
    if order:
        return redirect("restaurant:pos_order", pk=order.pk)
    kind = "room" if table.area and table.area.kind == "room" else "dine_in"
    return _order_screen(request, table=table, order_type=kind, opened_as_owner=as_owner)


@restaurant_required("pos")
def pos_new(request, kind):
    if kind not in ("takeaway", "delivery"):
        return redirect("restaurant:pos")
    if kind == "delivery" and not request.restaurant.has_feature("delivery"):
        messages.error(request, "Home delivery is not part of your plan. Upgrade in Plan & Billing.")
        return redirect("restaurant:pos")
    return _order_screen(request, order_type=kind)


@restaurant_required("pos")
def pos_order(request, pk):
    order = get_order(request, pk)
    as_owner = False
    if order.table_id and order.is_open:
        allowed, as_owner = _check_table_lock(request, order.table)
        if not allowed:
            messages.error(request, f"Table {order.table.name} is being served by {order.table.locked_by.display_name} right now.")
            return redirect("restaurant:pos")
    return _order_screen(request, table=order.table, order=order, opened_as_owner=as_owner)


@restaurant_required("pos")
@require_POST
def pos_send(request):
    r = request.restaurant
    user = request.user
    try:
        raw = json.loads(request.POST.get("cart") or "[]")
    except ValueError:
        raw = []
    cart = parse_cart(r, raw)
    order_id = request.POST.get("order_id")
    table_id = request.POST.get("table_id")
    order_type = request.POST.get("order_type") or "dine_in"
    if not cart:
        messages.error(request, "Add at least one item before sending the KOT.")
        if order_id:
            return redirect("restaurant:pos_order", pk=order_id)
        if table_id:
            return redirect("restaurant:pos_table", pk=table_id)
        return redirect("restaurant:pos_new", kind=order_type if order_type in ("takeaway", "delivery") else "takeaway")

    table = None
    order = None
    if order_id:
        order = get_order(request, order_id)
        table = order.table
        if not order.is_open:
            messages.error(request, "This order is already closed.")
            return redirect("restaurant:pos_order", pk=order.pk)
    elif table_id:
        table = get_object_or_404(Table, pk=table_id, restaurant=r)
        order = table.open_order

    if order is not None and request.POST.get("confirm_dup") != "1":
        dups = find_recent_duplicates(order, cart, user)
        if dups:
            request.session["dup_cart"] = {"order": order.id, "cart": raw, "dups": dups}
            return redirect("restaurant:pos_order", pk=order.pk)

    if order is None:
        if order_type == "delivery":
            phone = request.POST.get("customer_phone", "").strip()
            address = request.POST.get("delivery_address", "").strip()
            if not phone or not address:
                messages.error(request, "Enter the customer's mobile number and address for delivery.")
                return redirect("restaurant:pos_new", kind="delivery")
        if table is not None:
            order_type = "room" if table.area and table.area.kind == "room" else "dine_in"
        elif order_type not in ("takeaway", "delivery"):
            order_type = "takeaway"
        name = request.POST.get("customer_name", "").strip()
        phone = request.POST.get("customer_phone", "").strip()
        address = request.POST.get("delivery_address", "").strip()
        order = Order(
            restaurant=r, order_type=order_type, source="pos", table=table, status="accepted",
            customer_name=name, customer_phone=phone, delivery_address=address,
            guests=max(1, int(request.POST.get("guests") or 1)), note=request.POST.get("note", "")[:255],
            created_by=user,
        )
        if phone:
            order.customer = get_or_create_customer(r, phone, name, address)
        order.save()

    kot = add_items(order, cart, user, send=True)
    if table is not None:
        table.status = "occupied"
        if not table.locked_by_id:
            table.locked_by = user
            table.locked_at = timezone.now()
        table.save(update_fields=["status", "locked_by", "locked_at"])
    messages.success(request, f"KOT #{kot} sent to the kitchen.")
    resp = redirect("restaurant:pos_order", pk=order.pk)
    resp["Location"] += f"?kot={kot}"
    return resp


@restaurant_required("pos")
@require_POST
def pos_item_cancel(request, pk, item_pk):
    order = get_order(request, pk)
    item = get_object_or_404(OrderItem, pk=item_pk, order=order)
    if request.user.role not in CAN_CANCEL_ITEMS:
        messages.error(request, "Only the owner or a manager can cancel items.")
        return redirect("restaurant:pos_order", pk=pk)
    item.kot_status = "cancelled"
    item.status_changed_at = timezone.now()
    item.save(update_fields=["kot_status", "status_changed_at"])
    order.recalc()
    sync_order_status_from_items(order)
    log_activity(request, "Item cancelled", f"{item.qty} × {item.name} on #{order.number}")
    messages.success(request, f"{item.name} cancelled.")
    return redirect("restaurant:pos_order", pk=pk)


@restaurant_required("pos")
@require_POST
def pos_serve(request, pk):
    order = get_order(request, pk)
    n = order.items.filter(kot_status="ready").update(kot_status="served", status_changed_at=timezone.now())
    sync_order_status_from_items(order)
    messages.success(request, f"{n} item(s) marked as served." if n else "Nothing is ready to serve yet.")
    return redirect("restaurant:pos_order", pk=pk)


@restaurant_required("pos")
@require_POST
def pos_complete(request, pk):
    """Hand over a prepaid order (e.g. paid online) and close it."""
    order = get_order(request, pk)
    if order.payment_status != "paid":
        messages.error(request, "Take the payment before closing this order.")
        return redirect("restaurant:pos_order", pk=pk)
    order.items.filter(kot_status__in=["new", "preparing", "ready"]).update(kot_status="served", status_changed_at=timezone.now())
    order.status = "completed"
    order.completed_at = timezone.now()
    order.save(update_fields=["status", "completed_at", "updated_at"])
    if order.table_id:
        release_table(order.table)
    messages.success(request, f"#{order.number} handed over and closed.")
    return redirect("restaurant:pos")


@restaurant_required("pos")
@require_POST
def pos_discount(request, pk):
    order = get_order(request, pk)
    if request.user.role not in CAN_DISCOUNT:
        messages.error(request, "Your role cannot give discounts.")
        return redirect("restaurant:pos_order", pk=pk)
    mode = request.POST.get("mode")
    order.recalc(save=False)
    if mode == "coupon":
        code = request.POST.get("coupon", "").strip().upper()
        coupon = Coupon.objects.filter(restaurant=request.restaurant, code=code).first()
        if not coupon or not coupon.is_valid_for(order.subtotal):
            messages.error(request, "That coupon is not valid for this bill.")
            return redirect("restaurant:pos_order", pk=pk)
        order.discount = coupon.discount_for(order.subtotal)
        order.coupon_code = coupon.code
        coupon.times_used += 1
        coupon.save(update_fields=["times_used"])
    elif mode == "percent":
        pct = min(Decimal("100"), max(Decimal("0"), _dec(request.POST.get("value"))))
        order.discount = (order.subtotal * pct / 100).quantize(Decimal("0.01"))
        order.coupon_code = ""
    else:
        order.discount = min(order.subtotal, max(Decimal("0"), _dec(request.POST.get("value"))))
        order.coupon_code = ""
    order.recalc()
    log_activity(request, "Discount given", f"₹{order.discount} on #{order.number}")
    messages.success(request, f"Discount of ₹{order.discount} applied.")
    return redirect("restaurant:pos_order", pk=pk)


@restaurant_required("pos")
@require_POST
def pos_bill(request, pk):
    order = get_order(request, pk)
    if not order.active_items.exists():
        messages.error(request, "There is nothing to bill yet.")
        return redirect("restaurant:pos_order", pk=pk)
    mark_billed(order)
    log_activity(request, "Bill printed", f"#{order.number} · ₹{order.total}")
    resp = redirect("restaurant:bill_print", pk=pk)
    resp["Location"] += "?print=1"
    return resp


@restaurant_required("pos")
@require_POST
def pos_pay(request, pk):
    order = get_order(request, pk)
    order.recalc()
    methods = request.POST.getlist("method")
    amounts = request.POST.getlist("amount")
    tendered_cash = _dec(request.POST.get("tendered"))
    valid = dict(Payment.METHODS)
    lines = []
    for method, amount in zip(methods, amounts):
        amt = _dec(amount)
        if method in valid and amt > 0:
            lines.append([method, amt, None, request.POST.get("reference", "")])
    if not lines:
        messages.error(request, "Enter the amount received.")
        return redirect("restaurant:pos_order", pk=pk)
    if len(lines) > 1 and not request.restaurant.has_feature("split_billing"):
        messages.error(request, "Split billing is not part of your plan.")
        return redirect("restaurant:pos_order", pk=pk)
    balance = order.balance
    change = Decimal("0")
    total_in = sum(line[1] for line in lines)
    if total_in > balance:
        # Extra cash becomes change; never record more than the balance.
        over = total_in - balance
        for line in lines:
            if line[0] == "cash" and over > 0:
                cut = min(over, line[1])
                line[1] -= cut
                over -= cut
                change += cut
        if over > 0:
            messages.error(request, "The amount is more than the balance. Check the figures.")
            return redirect("restaurant:pos_order", pk=pk)
    for line in lines:
        if line[0] == "cash":
            line[2] = tendered_cash or (line[1] + change)
    if not order.bill_no:
        mark_billed(order)
    record_payments(order, [tuple(line) for line in lines if line[1] > 0], request.user)
    log_activity(request, "Payment received", f"#{order.number} · ₹{sum(l[1] for l in lines)}")
    if order.payment_status == "paid":
        msg = f"Payment complete for #{order.number}."
        if change > 0:
            msg += f" Give back ₹{change}."
        messages.success(request, msg)
        if order.order_type == "delivery" and order.status != "completed":
            return redirect("restaurant:delivery")
        return redirect("restaurant:pos")
    messages.info(request, f"Part payment saved. Balance ₹{order.balance}.")
    return redirect("restaurant:pos_order", pk=pk)


@restaurant_required("pos")
@require_POST
def pos_cancel_order(request, pk):
    order = get_order(request, pk)
    if request.user.role not in CAN_CANCEL_ITEMS:
        messages.error(request, "Only the owner or a manager can cancel orders.")
        return redirect("restaurant:pos_order", pk=pk)
    if order.payments.exists():
        messages.error(request, "This order has payments. Refund them before cancelling.")
        return redirect("restaurant:pos_order", pk=pk)
    order.status = "cancelled"
    order.note = (order.note + " | Cancelled: " + request.POST.get("reason", "")).strip(" |")[:255]
    order.save()
    order.items.exclude(kot_status="served").update(kot_status="cancelled")
    if order.table_id:
        release_table(order.table)
    log_activity(request, "Order cancelled", f"#{order.number}")
    messages.success(request, f"Order #{order.number} cancelled.")
    return redirect("restaurant:pos")


@restaurant_required("pos")
@require_POST
def pos_table_close(request, pk):
    table = get_object_or_404(Table, pk=pk, restaurant=request.restaurant)
    if table.locked_by_id == request.user.id or request.user.role in CAN_OVERRIDE_TABLE_LOCK:
        table.locked_by = None
        table.locked_at = None
        table.save(update_fields=["locked_by", "locked_at"])
    return redirect("restaurant:pos")


@restaurant_required("pos")
@require_POST
def pos_table_status(request, pk):
    table = get_object_or_404(Table, pk=pk, restaurant=request.restaurant)
    status = request.POST.get("status")
    if status not in ("free", "reserved", "cleaning"):
        messages.error(request, "Unknown table status.")
    elif table.open_order:
        messages.error(request, f"{table.name} has an open order. Settle it first.")
    else:
        table.status = status
        table.locked_by = None
        table.save(update_fields=["status", "locked_by"])
        messages.success(request, f"{table.name} is now {table.get_status_display().lower()}.")
    return redirect("restaurant:pos")


@restaurant_required("pos")
def kot_print(request, pk, kot_no):
    order = get_order(request, pk)
    items = order.items.filter(kot_no=kot_no).exclude(kot_status="cancelled")
    return render(request, "restaurant/print_kot.html", {"order": order, "items": items, "kot_no": kot_no})
