from django.contrib import messages
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required

from ..models import Order, WaiterCall
from ..services import day_stats, smart_insights, top_sellers
from .common import back


@restaurant_required("dashboard")
def dashboard(request):
    r = request.restaurant
    today = timezone.localdate()
    hour = timezone.localtime().hour
    greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    live = (
        Order.objects.filter(restaurant=r, status__in=Order.OPEN_STATUSES)
        .select_related("table").order_by("-created_at")[:8]
    )
    insights = smart_insights(r) if r.has_feature("insights") else []
    return render(request, "restaurant/dashboard.html", {
        "greeting": greeting,
        "stats": day_stats(r, today),
        "live_orders": live,
        "top_sellers": top_sellers(r, today, today),
        "insights": insights,
        "awaiting": Order.objects.filter(restaurant=r, status="awaiting").select_related("table")[:5],
    })


@restaurant_required()
@require_POST
def resolve_call(request, pk):
    call = get_object_or_404(WaiterCall, pk=pk, restaurant=request.restaurant)
    call.resolved = True
    call.save(update_fields=["resolved"])
    messages.success(request, f"Call from {call.table.name} marked as attended.")
    return back(request, "restaurant:dashboard")
