"""Customers, inventory, reports and marketing."""
import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required
from core.utils import log_activity, public_base_url

from ..forms import CouponForm, CustomerForm, InventoryItemForm, SeoForm, StockMovementForm
from ..models import Coupon, Customer, InventoryItem, Order, OrderItem, StockMovement
from ..services import hourly_sales, payment_split, smart_insights, top_sellers
from .common import csv_response


# ------------------------------------------------------------- customers
@restaurant_required("customers")
def customers(request):
    r = request.restaurant
    q = request.GET.get("q", "").strip()
    qs = Customer.objects.filter(restaurant=r)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    sort = request.GET.get("sort", "recent")
    qs = qs.order_by({"spent": "-total_spent", "points": "-loyalty_points", "visits": "-visits"}.get(sort, "-last_visit"))
    if request.GET.get("export"):
        rows = [["Name", "Phone", "Email", "Visits", "Total spent", "Points", "Last visit"]]
        rows += [[c.name, c.phone, c.email, c.visits, c.total_spent, c.loyalty_points,
                  c.last_visit and timezone.localtime(c.last_visit).strftime("%d-%m-%Y")] for c in qs]
        return csv_response("customers.csv", rows)
    agg = Customer.objects.filter(restaurant=r).aggregate(n=Count("id"), pts=Sum("loyalty_points"), spent=Sum("total_spent"))
    month_ago = timezone.now() - timedelta(days=30)
    return render(request, "restaurant/customers.html", {
        "page": Paginator(qs, 30).get_page(request.GET.get("page")),
        "q": q, "sort": sort, "agg": agg,
        "new_month": Customer.objects.filter(restaurant=r, created_at__gte=month_ago).count(),
        "repeat": Customer.objects.filter(restaurant=r, visits__gte=2).count(),
    })


@restaurant_required("customers")
def customer_edit(request, pk=None):
    r = request.restaurant
    customer = get_object_or_404(Customer, pk=pk, restaurant=r) if pk else None
    form = CustomerForm(request.POST or None, instance=customer, restaurant=r)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.restaurant = r
        obj.save()
        messages.success(request, f"{obj} saved.")
        return redirect("restaurant:customer_detail", pk=obj.pk)
    return render(request, "restaurant/customer_form.html", {"form": form, "customer": customer})


@restaurant_required("customers")
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk, restaurant=request.restaurant)
    orders = customer.orders.order_by("-created_at")[:25]
    favourites = (
        OrderItem.objects.filter(order__customer=customer).exclude(kot_status="cancelled")
        .values("name").annotate(q=Sum("qty")).order_by("-q")[:5]
    )
    return render(request, "restaurant/customer_detail.html", {"c": customer, "orders": orders, "favourites": favourites})


# ------------------------------------------------------------- inventory
@restaurant_required("inventory")
def inventory(request):
    r = request.restaurant
    qs = InventoryItem.objects.filter(restaurant=r)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(name__icontains=q)
    if request.GET.get("low"):
        qs = qs.filter(quantity__lte=F("reorder_level"))
    items = list(qs)
    return render(request, "restaurant/inventory.html", {
        "items": items, "q": q, "low_only": bool(request.GET.get("low")),
        "low_count": InventoryItem.objects.filter(restaurant=r, quantity__lte=F("reorder_level")).count(),
        "stock_value": sum((i.stock_value for i in InventoryItem.objects.filter(restaurant=r)), 0),
        "form": InventoryItemForm(), "move_form": StockMovementForm(),
        "recent": StockMovement.objects.filter(item__restaurant=r).select_related("item", "created_by")[:10],
    })


@restaurant_required("inventory")
def inventory_edit(request, pk=None):
    r = request.restaurant
    item = get_object_or_404(InventoryItem, pk=pk, restaurant=r) if pk else None
    form = InventoryItemForm(request.POST or None, instance=item)
    if request.method == "POST":
        if request.POST.get("delete") and item:
            item.delete()
            messages.success(request, "Stock item deleted.")
            return redirect("restaurant:inventory")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = r
            obj.save()
            messages.success(request, f"{obj.name} saved.")
            return redirect("restaurant:inventory")
    return render(request, "restaurant/inventory_form.html", {"form": form, "item": item})


@restaurant_required("inventory")
@require_POST
def inventory_move(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk, restaurant=request.restaurant)
    form = StockMovementForm(request.POST)
    if form.is_valid():
        mv = form.save(commit=False)
        if mv.reason in ("usage", "wastage") and mv.change > 0:
            mv.change = -mv.change
        mv.item = item
        mv.created_by = request.user
        mv.save()
        InventoryItem.objects.filter(pk=item.pk).update(quantity=F("quantity") + mv.change)
        log_activity(request, "Stock updated", f"{item.name}: {mv.change:+} {item.unit} ({mv.get_reason_display()})")
        messages.success(request, f"{item.name} stock updated.")
    else:
        messages.error(request, "Enter a valid quantity.")
    return redirect("restaurant:inventory")


# --------------------------------------------------------------- reports
def _parse_date(value, default):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


@restaurant_required("reports")
def reports(request):
    r = request.restaurant
    today = timezone.localdate()
    preset = request.GET.get("range", "")
    if preset == "7d":
        start, end = today - timedelta(days=6), today
    elif preset == "30d":
        start, end = today - timedelta(days=29), today
    elif preset == "month":
        start, end = today.replace(day=1), today
    else:
        start = _parse_date(request.GET.get("from"), today)
        end = _parse_date(request.GET.get("to"), start)
    if end < start:
        start, end = end, start

    orders = Order.objects.filter(restaurant=r, created_at__date__gte=start, created_at__date__lte=end)
    completed = orders.filter(status="completed")
    agg = completed.aggregate(sales=Sum("total"), disc=Sum("discount"), tax=Sum("tax"), sc=Sum("service_charge"), guests=Sum("guests"))
    count = completed.count()

    item_rows = list(
        OrderItem.objects.filter(order__in=completed).exclude(kot_status="cancelled")
        .values("name").annotate(sold=Sum("qty"), orders=Count("order", distinct=True),
                                 amount=Sum(F("price") * F("qty"), output_field=DecimalField(max_digits=14, decimal_places=2)))
        .order_by("-amount")
    )
    if request.GET.get("export") == "items":
        rows = [["Item", "Quantity", "Orders", "Amount"]] + [[i["name"], i["sold"], i["orders"], i["amount"]] for i in item_rows]
        rows += [[], ["Total quantity", sum(i["sold"] for i in item_rows)], ["Discounts", agg["disc"] or 0],
                 ["Net sales", agg["sales"] or 0]]
        for p in payment_split(r, start, end):
            rows.append([p["method"], p["amount"]])
        return csv_response(f"item-sales-{start}-to-{end}.csv", rows)
    if request.GET.get("export") == "orders":
        rows = [["Order", "Bill", "Date", "Type", "Source", "Place", "Customer", "Status", "Total"]]
        for o in orders.select_related("table"):
            rows.append([o.number, o.bill_no, timezone.localtime(o.created_at).strftime("%d-%m-%Y %H:%M"),
                         o.get_order_type_display(), o.get_source_display(), o.place_label, o.customer_name,
                         o.get_status_display(), o.total])
        return csv_response(f"orders-{start}-to-{end}.csv", rows)

    daily = (
        completed.annotate(d=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
        .values("d").annotate(s=Sum("total"), n=Count("id")).order_by("d")
    )
    daily_map = {row["d"]: float(row["s"] or 0) for row in daily}
    days = (end - start).days + 1
    trend_labels, trend_values = [], []
    for i in range(min(days, 62)):
        d = start + timedelta(days=i)
        trend_labels.append(d.strftime("%d %b"))
        trend_values.append(daily_map.get(d, 0))

    by_type = list(completed.values("order_type").annotate(n=Count("id"), s=Sum("total")).order_by("-s"))
    type_labels = dict(Order.TYPE_CHOICES)
    for row in by_type:
        row["label"] = type_labels.get(row["order_type"], row["order_type"])
    by_source = list(completed.values("source").annotate(n=Count("id"), s=Sum("total")).order_by("-s"))
    src_labels = dict(Order.SOURCE_CHOICES)
    for row in by_source:
        row["label"] = src_labels.get(row["source"], row["source"])

    by_staff = list(
        completed.exclude(created_by=None).values("created_by__first_name", "created_by__username")
        .annotate(n=Count("id"), s=Sum("total")).order_by("-s")[:8]
    )
    split = payment_split(r, start, end)
    return render(request, "restaurant/reports.html", {
        "start": start, "end": end, "preset": preset,
        "sales": agg["sales"] or 0, "discounts": agg["disc"] or 0, "tax": agg["tax"] or 0,
        "service": agg["sc"] or 0, "guests": agg["guests"] or 0, "count": count,
        "avg": (agg["sales"] / count) if count and agg["sales"] else 0,
        "cancelled": orders.filter(status__in=["cancelled", "rejected"]).count(),
        "items": item_rows, "total_qty": sum(i["sold"] for i in item_rows),
        "items_total": sum((i["amount"] or 0 for i in item_rows), 0),
        "split": split, "split_total": sum((p["amount"] for p in split), 0),
        "by_type": by_type, "by_source": by_source, "by_staff": by_staff,
        "trend_labels": json.dumps(trend_labels), "trend_values": json.dumps(trend_values),
        "hourly": json.dumps(hourly_sales(r, end)),
        "top": top_sellers(r, start, end, limit=5),
        "insights": smart_insights(r) if r.has_feature("insights") else [],
    })


# ------------------------------------------------------------- marketing
@restaurant_required("marketing")
def marketing(request):
    r = request.restaurant
    seo_form = SeoForm(request.POST or None, instance=r, prefix="seo")
    if request.method == "POST" and seo_form.is_valid():
        seo_form.save()
        messages.success(request, "Online store SEO saved.")
        return redirect("restaurant:marketing")
    base = public_base_url(request)
    return render(request, "restaurant/marketing.html", {
        "coupons": Coupon.objects.filter(restaurant=r),
        "coupon_form": CouponForm(),
        "seo_form": seo_form,
        "store_url": f"{base}/s/{r.slug}/",
        "customers_count": r.customers.count(),
        "birthdays": r.customers.filter(birthday__month=timezone.localdate().month).count(),
    })


@restaurant_required("marketing")
def coupon_edit(request, pk=None):
    r = request.restaurant
    coupon = get_object_or_404(Coupon, pk=pk, restaurant=r) if pk else None
    form = CouponForm(request.POST or None, instance=coupon)
    if request.method == "POST":
        if request.POST.get("delete") and coupon:
            coupon.delete()
            messages.success(request, "Coupon deleted.")
            return redirect("restaurant:marketing")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = r
            if Coupon.objects.filter(restaurant=r, code=obj.code).exclude(pk=obj.pk).exists():
                form.add_error("code", "This code already exists.")
            else:
                obj.save()
                messages.success(request, f"Coupon {obj.code} saved.")
                return redirect("restaurant:marketing")
    return render(request, "restaurant/coupon_form.html", {"form": form, "coupon": coupon})
