"""Order, payment and insight helpers for the restaurant panel."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, F, Max, Q, Sum
from django.db.models.functions import ExtractHour
from django.utils import timezone

from .models import Customer, InventoryItem, MenuItem, Order, OrderItem, Payment


def get_or_create_customer(restaurant, phone, name="", address="", email=""):
    phone = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
    if not phone:
        return None
    customer, created = Customer.objects.get_or_create(
        restaurant=restaurant, phone=phone, defaults={"name": name or "", "address": address or "", "email": email or ""}
    )
    changed = []
    if name and not customer.name:
        customer.name = name
        changed.append("name")
    if address and address != customer.address:
        customer.address = address
        changed.append("address")
    if changed:
        customer.save(update_fields=changed)
    return customer


def next_kot_no(order):
    return (order.items.aggregate(m=Max("kot_no"))["m"] or 0) + 1


def find_recent_duplicates(order, cart, user, seconds=120):
    """Items in the cart that someone else added to this order moments ago."""
    if order is None:
        return []
    since = timezone.now() - timedelta(seconds=seconds)
    recent = order.items.filter(created_at__gte=since).exclude(kot_status="cancelled").exclude(added_by=user)
    recent_ids = {i.menu_item_id: i for i in recent if i.menu_item_id}
    dups = []
    for line in cart:
        hit = recent_ids.get(line["menu_item"].id)
        if hit:
            dups.append({"name": hit.name, "by": hit.added_by.display_name if hit.added_by else "someone"})
    return dups


@transaction.atomic
def add_items(order, cart, user, send=True):
    """cart: list of {menu_item, qty, note}. Returns the KOT number used."""
    kot_no = next_kot_no(order) if send else 0
    now = timezone.now()
    for line in cart:
        mi = line["menu_item"]
        OrderItem.objects.create(
            order=order, menu_item=mi, name=mi.name, price=mi.price, qty=max(1, int(line.get("qty") or 1)),
            note=(line.get("note") or "")[:120], food_type=mi.food_type, station=mi.station,
            kot_status="new" if send else "pending", kot_no=kot_no, added_by=user,
            sent_at=now if send else None, status_changed_at=now,
        )
    if order.status in ("served", "ready") and send:
        order.status = "accepted"
    order.recalc()
    return kot_no


def parse_cart(restaurant, raw_lines):
    """raw_lines: list of dicts with id/qty/note from the POS or storefront."""
    ids = []
    for line in raw_lines or []:
        try:
            ids.append(int(line.get("id")))
        except (TypeError, ValueError):
            continue
    items = {m.id: m for m in MenuItem.objects.filter(restaurant=restaurant, id__in=ids, is_available=True)}
    cart = []
    for line in raw_lines or []:
        try:
            mi = items.get(int(line.get("id")))
            qty = int(line.get("qty") or 1)
        except (TypeError, ValueError):
            continue
        if mi and qty > 0:
            cart.append({"menu_item": mi, "qty": min(qty, 99), "note": str(line.get("note") or "")[:120]})
    return cart


def sync_order_status_from_items(order):
    statuses = set(order.active_items.exclude(kot_status="pending").values_list("kot_status", flat=True))
    if not statuses or order.status in ("completed", "cancelled", "rejected", "awaiting", "out_for_delivery"):
        return
    if statuses <= {"served"}:
        new = "served"
    elif statuses <= {"ready", "served"}:
        new = "ready"
    elif "preparing" in statuses or "ready" in statuses:
        new = "preparing"
    else:
        new = "accepted"
    if new == "served" and order.payment_status == "paid" and order.order_type != "delivery":
        order.status = "completed"
        order.completed_at = timezone.now()
        order.save(update_fields=["status", "completed_at", "updated_at"])
        if order.table_id:
            release_table(order.table)
        return
    if new != order.status:
        order.status = new
        order.save(update_fields=["status", "updated_at"])


def mark_billed(order):
    if not order.bill_no:
        today = timezone.localdate()
        count = Order.objects.filter(restaurant=order.restaurant, billed_at__date=today).exclude(bill_no="").count() + 1
        order.bill_no = f"B{today:%y%m%d}-{count:03d}"
        order.billed_at = timezone.now()
    order.recalc(save=False)
    order.save()
    if order.table_id and order.table.status in ("occupied", "free"):
        order.table.status = "billed"
        order.table.save(update_fields=["status"])


@transaction.atomic
def record_payments(order, lines, user):
    """lines: list of (method, amount, tendered, reference). Completes the order when settled."""
    for method, amount, tendered, reference in lines:
        if amount and amount > 0:
            Payment.objects.create(order=order, method=method, amount=amount, tendered=tendered,
                                   reference=reference or "", created_by=user)
    order.refresh_payment_status()
    if order.payment_status == "paid":
        complete_order(order)
    else:
        order.save(update_fields=["payment_status", "updated_at"])


def complete_order(order):
    if not order.bill_no:
        mark_billed(order)
    order.payment_status = "paid"
    if order.order_type != "delivery" or order.delivery_status == "delivered":
        order.status = "completed"
        order.completed_at = timezone.now()
    order.save()
    order.items.filter(kot_status__in=["ready"]).update(kot_status="served")
    if order.table_id:
        table = order.table
        if not table.orders.filter(status__in=Order.OPEN_STATUSES).exclude(pk=order.pk).exists():
            table.status = "free"
            table.locked_by = None
            table.locked_at = None
            table.save(update_fields=["status", "locked_by", "locked_at"])
    award_loyalty(order)


def award_loyalty(order):
    r = order.restaurant
    customer = order.customer
    if customer is None and order.customer_phone:
        customer = get_or_create_customer(r, order.customer_phone, order.customer_name, order.delivery_address)
        if customer:
            order.customer = customer
            order.save(update_fields=["customer"])
    if customer is None:
        return
    customer.visits = F("visits") + 1
    customer.total_spent = F("total_spent") + order.total
    customer.last_visit = timezone.now()
    if r.loyalty_enabled:
        customer.loyalty_points = F("loyalty_points") + int(order.total // 100) * r.loyalty_points_per_100
    customer.save()


def release_table(table):
    table.locked_by = None
    table.locked_at = None
    if not table.orders.filter(status__in=Order.OPEN_STATUSES).exists() and table.status in ("occupied", "billed"):
        table.status = "free"
    table.save(update_fields=["locked_by", "locked_at", "status"])


# ---------------------------------------------------------------- insights
def day_stats(restaurant, day=None):
    day = day or timezone.localdate()
    orders = Order.objects.filter(restaurant=restaurant, created_at__date=day)
    completed = orders.filter(status="completed")
    sales = completed.aggregate(s=Sum("total"), d=Sum("discount"), g=Sum("guests"))
    count = completed.count()
    return {
        "sales": sales["s"] or Decimal("0"),
        "discounts": sales["d"] or Decimal("0"),
        "guests": sales["g"] or 0,
        "completed": count,
        "cancelled": orders.filter(status__in=["cancelled", "rejected"]).count(),
        "avg": (sales["s"] / count) if count and sales["s"] else Decimal("0"),
        "running": Order.objects.filter(restaurant=restaurant, status__in=Order.OPEN_STATUSES).count(),
        "orders": orders.count(),
    }


def top_sellers(restaurant, start, end, limit=5):
    return list(
        OrderItem.objects.filter(
            order__restaurant=restaurant, order__status="completed",
            order__created_at__date__gte=start, order__created_at__date__lte=end,
        ).exclude(kot_status="cancelled")
        .values("name").annotate(sold=Sum("qty"), orders=Count("order", distinct=True), amount=Sum(F("price") * F("qty"), output_field=DecimalField(max_digits=14, decimal_places=2)))
        .order_by("-sold")[:limit]
    )


def smart_insights(restaurant):
    """Plain-language tips computed from the last 30 days."""
    today = timezone.localdate()
    start = today - timedelta(days=30)
    orders = Order.objects.filter(restaurant=restaurant, status="completed", created_at__date__gte=start)
    tips = []
    if not orders.exists():
        return ["Complete a few orders and FoodyX will start suggesting ways to grow sales here."]

    hours = Counter(
        orders.annotate(h=ExtractHour("created_at", tzinfo=timezone.get_current_timezone())).values_list("h", flat=True)
    )
    if hours:
        peak = hours.most_common(1)[0][0]
        tips.append(f"Your peak hour is {peak:02d}:00 — schedule extra staff and pre-prep for it.")

    best = top_sellers(restaurant, start, today, limit=1)
    if best:
        tips.append(f"‘{best[0]['name']}’ is your best seller — feature it on the QR menu and online store.")

    sold_ids = set(
        OrderItem.objects.filter(order__in=orders).exclude(menu_item=None).values_list("menu_item_id", flat=True)
    )
    slow = list(
        restaurant.menu_items.filter(is_available=True).exclude(id__in=sold_ids).values_list("name", flat=True)[:3]
    )
    if slow:
        tips.append(f"Slow movers in the last 30 days: {', '.join(slow)}. Consider a combo or removing them.")

    total = orders.count()
    digital = orders.filter(source__in=["qr", "online"]).count()
    share = (digital * 100 // total) if total else 0
    if share < 15:
        tips.append("Less than 15% of sales come from QR/online. Print table QR codes and share your store link on WhatsApp.")
    else:
        tips.append(f"{share}% of orders come from QR and online — great! Keep the menu photos fresh.")

    low = list(InventoryItem.objects.filter(restaurant=restaurant, quantity__lte=F("reorder_level")).values_list("name", flat=True)[:4])
    if low:
        tips.append(f"Re-order soon: {', '.join(low)}.")

    discount_total = orders.aggregate(d=Sum("discount"))["d"] or 0
    sales_total = orders.aggregate(s=Sum("total"))["s"] or 0
    if sales_total and discount_total * 100 / sales_total > 10:
        tips.append("Discounts are above 10% of sales — review who is giving them in Bills.")
    return tips


def hourly_sales(restaurant, day):
    rows = (
        Order.objects.filter(restaurant=restaurant, status="completed", created_at__date=day)
        .annotate(h=ExtractHour("created_at", tzinfo=timezone.get_current_timezone()))
        .values("h").annotate(s=Sum("total")).order_by("h")
    )
    data = {r["h"]: float(r["s"] or 0) for r in rows}
    return [data.get(h, 0) for h in range(24)]


def payment_split(restaurant, start, end):
    rows = (
        Payment.objects.filter(order__restaurant=restaurant, created_at__date__gte=start, created_at__date__lte=end)
        .values("method").annotate(s=Sum("amount")).order_by("-s")
    )
    labels = dict(Payment.METHODS)
    return [{"method": labels.get(r["method"], r["method"]), "code": r["method"], "amount": r["s"] or 0} for r in rows]


def awaiting_qr_count(restaurant):
    return Order.objects.filter(restaurant=restaurant, status="awaiting").count()


def search_orders(qs, q):
    return qs.filter(
        Q(number__icontains=q) | Q(bill_no__icontains=q) | Q(customer_name__icontains=q)
        | Q(customer_phone__icontains=q) | Q(table__name__iexact=q)
    )


@transaction.atomic
def accept_order(order, user=None):
    """Accept a QR/online order. A QR order for a table that already has a
    running order is added to that order, so the table keeps one bill."""
    now = timezone.now()
    target = order
    if order.table_id:
        existing = (
            order.table.orders.filter(status__in=Order.OPEN_STATUSES).exclude(status="awaiting")
            .exclude(pk=order.pk).order_by("created_at").first()
        )
        if existing:
            target = existing
    kot = next_kot_no(target)
    order.items.filter(kot_status="pending").update(
        order=target, kot_status="new", sent_at=now, kot_no=kot, status_changed_at=now
    )
    if target is not order:
        order.status = "merged"
        order.merged_into = target
        order.recalc(save=False)
        order.save()
        if target.status in ("ready", "served"):
            target.status = "accepted"
        target.recalc()
    else:
        order.status = "accepted"
        order.save(update_fields=["status", "updated_at"])
    if order.table_id:
        t = order.table
        if t.status in ("free", "reserved", "cleaning"):
            t.status = "occupied"
            t.save(update_fields=["status"])
    return target
