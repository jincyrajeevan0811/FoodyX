from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required
from core.utils import log_activity

from ..models import Order, Payment
from ..services import complete_order, record_payments
from .common import get_order

User = get_user_model()


def _riders(restaurant):
    return (
        User.objects.filter(restaurant=restaurant, role="rider", is_active=True)
        .annotate(active=Count("deliveries", filter=Q(deliveries__status__in=Order.OPEN_STATUSES)))
        .order_by("-is_online", "active", "first_name")
    )


@restaurant_required("delivery")
def delivery(request):
    r = request.restaurant
    open_orders = (
        Order.objects.filter(restaurant=r, order_type="delivery", status__in=Order.OPEN_STATUSES)
        .select_related("rider", "customer").order_by("created_at")
    )
    today = timezone.localdate()
    delivered_today = Order.objects.filter(restaurant=r, order_type="delivery", delivery_status="delivered",
                                           completed_at__date=today)
    columns = [
        ("unassigned", "Waiting for rider", [o for o in open_orders if o.delivery_status == "unassigned"]),
        ("assigned", "Rider assigned", [o for o in open_orders if o.delivery_status in ("assigned", "accepted")]),
        ("picked", "Out for delivery", [o for o in open_orders if o.delivery_status == "picked"]),
    ]
    cod_pending = [
        o for o in delivered_today if o.payments.filter(method="cash", reference="COD").exists()
    ]
    return render(request, "restaurant/delivery.html", {
        "columns": columns,
        "riders": _riders(r),
        "delivered_today": delivered_today.count(),
        "cod_today": sum((o.total for o in cod_pending), 0),
    })


@restaurant_required("delivery")
@require_POST
def delivery_assign(request, pk):
    order = get_order(request, pk)
    riders = _riders(request.restaurant)
    rider_id = request.POST.get("rider")
    if rider_id == "auto":
        rider = riders.filter(is_online=True).first() or riders.first()
    else:
        rider = riders.filter(pk=rider_id).first()
    if rider is None:
        messages.error(request, "No rider available. Add riders in Staff & Roles.")
        return redirect("restaurant:delivery")
    order.rider = rider
    order.delivery_status = "assigned"
    order.save(update_fields=["rider", "delivery_status", "updated_at"])
    log_activity(request, "Rider assigned", f"#{order.number} → {rider.display_name}")
    messages.success(request, f"#{order.number} assigned to {rider.display_name}.")
    return redirect("restaurant:delivery")


# ------------------------------------------------------------------ rider
@restaurant_required("rider")
def rider(request):
    mine = (
        Order.objects.filter(restaurant=request.restaurant, rider=request.user, order_type="delivery")
        .exclude(delivery_status="delivered").exclude(status__in=["cancelled", "rejected"]).order_by("created_at")
    )
    done = Order.objects.filter(
        restaurant=request.restaurant, rider=request.user, delivery_status="delivered",
        completed_at__date=timezone.localdate(),
    )
    cash = sum((p.amount for o in done for p in o.payments.all() if p.reference == "COD"), 0)
    return render(request, "restaurant/rider.html", {"orders": mine, "done": done, "cash_in_hand": cash})


@restaurant_required("rider")
@require_POST
def rider_toggle(request):
    request.user.is_online = not request.user.is_online
    request.user.save(update_fields=["is_online"])
    messages.success(request, "You are online — new deliveries can come to you." if request.user.is_online else "You are offline.")
    return redirect("restaurant:rider")


@restaurant_required("rider")
@require_POST
def rider_action(request, pk):
    order = get_object_or_404(Order, pk=pk, restaurant=request.restaurant, rider=request.user)
    action = request.POST.get("action")
    if action == "accept" and order.delivery_status == "assigned":
        order.delivery_status = "accepted"
        order.save(update_fields=["delivery_status", "updated_at"])
        messages.success(request, f"You accepted #{order.number}.")
    elif action == "picked" and order.delivery_status in ("assigned", "accepted"):
        order.delivery_status = "picked"
        order.status = "out_for_delivery"
        order.save(update_fields=["delivery_status", "status", "updated_at"])
        messages.success(request, f"#{order.number} is out for delivery.")
    elif action == "delivered" and order.delivery_status == "picked":
        if request.POST.get("otp", "").strip() != order.delivery_otp:
            messages.error(request, "The delivery code doesn't match. Ask the customer again.")
            return redirect("restaurant:rider")
        order.delivery_status = "delivered"
        order.save(update_fields=["delivery_status", "updated_at"])
        if order.payment_status != "paid":
            record_payments(order, [("cash", order.balance, order.balance, "COD")], request.user)
        else:
            complete_order(order)
        log_activity(request, "Order delivered", f"#{order.number}")
        messages.success(request, f"#{order.number} delivered. Thank you!")
    else:
        messages.error(request, "That step is not available for this order.")
    return redirect("restaurant:rider")
