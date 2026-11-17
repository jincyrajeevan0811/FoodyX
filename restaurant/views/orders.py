from datetime import datetime

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required
from core.utils import log_activity

from ..models import Order
from ..services import accept_order, search_orders
from .common import back, csv_response, get_order


@restaurant_required("live_orders")
def live_orders(request):
    r = request.restaurant
    orders = (
        Order.objects.filter(restaurant=r, status__in=Order.OPEN_STATUSES)
        .select_related("table", "created_by", "rider").prefetch_related("items").order_by("created_at")
    )
    ctx = {"orders": orders, "open_total": orders.aggregate(s=Sum("total"))["s"] or 0}
    if request.GET.get("partial"):
        return render(request, "restaurant/partials/live_orders_list.html", ctx)
    return render(request, "restaurant/live_orders.html", ctx)


ORDER_TABS = [
    ("awaiting", "Awaiting acceptance"),
    ("active", "Active"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
    ("all", "All"),
]


@restaurant_required("orders")
def orders(request):
    r = request.restaurant
    tab = request.GET.get("tab") or ("awaiting" if Order.objects.filter(restaurant=r, status="awaiting").exists() else "active")
    qs = Order.objects.filter(restaurant=r).select_related("table", "created_by")
    if tab == "awaiting":
        qs = qs.filter(status="awaiting")
    elif tab == "active":
        qs = qs.filter(status__in=[s for s in Order.OPEN_STATUSES if s != "awaiting"])
    elif tab == "completed":
        qs = qs.filter(status="completed")
    elif tab == "cancelled":
        qs = qs.filter(status__in=["cancelled", "rejected"])
    source = request.GET.get("source", "")
    if source:
        qs = qs.filter(source=source)
    q = request.GET.get("q", "").strip()
    if q:
        qs = search_orders(qs, q)
    page = Paginator(qs.order_by("-created_at"), 25).get_page(request.GET.get("page"))
    counts = {
        "awaiting": Order.objects.filter(restaurant=r, status="awaiting").count(),
        "active": Order.objects.filter(restaurant=r, status__in=[s for s in Order.OPEN_STATUSES if s != "awaiting"]).count(),
    }
    return render(request, "restaurant/orders.html", {
        "page": page, "tab": tab, "tabs": ORDER_TABS, "q": q, "source": source, "counts": counts,
    })


@restaurant_required("orders")
def order_detail(request, pk):
    order = get_order(request, pk)
    return render(request, "restaurant/order_detail.html", {
        "order": order,
        "items": order.items.select_related("added_by"),
        "payments": order.payments.select_related("created_by"),
    })


@restaurant_required("orders")
@require_POST
def order_accept(request, pk):
    order = get_order(request, pk)
    if order.status != "awaiting":
        messages.info(request, "This order was already handled.")
        return back(request, "restaurant:orders")
    if request.POST.get("decision") == "reject":
        order.status = "rejected"
        order.save(update_fields=["status", "updated_at"])
        order.items.update(kot_status="cancelled")
        log_activity(request, "QR/online order rejected", f"#{order.number}")
        messages.success(request, f"Order #{order.number} rejected.")
    else:
        target = accept_order(order, request.user)
        if target != order:
            messages.info(request, f"Added to the running order #{target.number} on {order.table.name}.")
        log_activity(request, "QR/online order accepted", f"#{order.number}")
        messages.success(request, f"Order #{order.number} accepted and sent to the kitchen.")
    return back(request, "restaurant:orders")


# ----------------------------------------------------------------- bills
@restaurant_required("bills")
def bills(request):
    r = request.restaurant
    date_str = request.GET.get("date", "")
    q = request.GET.get("q", "").strip()
    qs = Order.objects.filter(restaurant=r).exclude(bill_no="").select_related("table")
    day = None
    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            day = None
    if q:
        qs = search_orders(qs, q)
    elif day:
        qs = qs.filter(billed_at__date=day)
    else:
        day = timezone.localdate()
        qs = qs.filter(billed_at__date=day)
    qs = qs.order_by("-billed_at")
    if request.GET.get("export"):
        rows = [["Bill no", "Order", "Date", "Place", "Customer", "Subtotal", "Discount", "Tax", "Total", "Payment"]]
        for o in qs:
            rows.append([o.bill_no, o.number, timezone.localtime(o.billed_at).strftime("%d-%m-%Y %H:%M"), o.place_label,
                         o.customer_name, o.subtotal, o.discount, o.tax, o.total, o.get_payment_status_display()])
        return csv_response(f"bills-{day or 'search'}.csv", rows)
    totals = qs.aggregate(t=Sum("total"), d=Sum("discount"))
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "restaurant/bills.html", {
        "page": page, "day": day, "q": q, "total": totals["t"] or 0, "discount": totals["d"] or 0,
    })


@restaurant_required()
def bill_print(request, pk):
    """Printable bill. Open to anyone who can see POS, bills or orders."""
    from core.permissions import user_modules

    if not ({"pos", "bills", "orders"} & user_modules(request.user)):
        return redirect("core:home_redirect")
    order = get_order(request, pk)
    return render(request, "restaurant/print_bill.html", {
        "order": order,
        "items": order.active_items,
        "payments": order.payments.all(),
        "auto_print": request.GET.get("print") == "1",
    })
