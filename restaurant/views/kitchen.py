from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required
from core.utils import log_activity

from ..models import OrderItem
from ..services import sync_order_status_from_items
from .common import get_order

FLOW = {"new": "preparing", "preparing": "ready", "ready": "served"}
RANK = {"new": 0, "preparing": 1, "ready": 2}


def _tickets(restaurant, station=""):
    items = (
        OrderItem.objects.filter(order__restaurant=restaurant, kot_status__in=["new", "preparing", "ready"],
                                 order__status__in=["accepted", "preparing", "ready", "served"])
        .select_related("order", "order__table", "added_by").order_by("sent_at", "id")
    )
    if station:
        items = items.filter(station__iexact=station)
    tickets = {}
    for it in items:
        key = (it.order_id, it.kot_no)
        t = tickets.get(key)
        if t is None:
            t = tickets[key] = {"order": it.order, "kot_no": it.kot_no, "items": [], "sent_at": it.sent_at or it.created_at}
        t["items"].append(it)
    now = timezone.now()
    out = []
    for t in tickets.values():
        t["status"] = min((i.kot_status for i in t["items"]), key=lambda s: RANK[s])
        mins = int((now - t["sent_at"]).total_seconds() // 60)
        t["minutes"] = mins
        t["tone"] = "red" if mins >= 20 else ("amber" if mins >= 10 else "ok")
        t["by"] = t["items"][0].added_by.display_name if t["items"][0].added_by else t["order"].get_source_display()
        out.append(t)
    out.sort(key=lambda t: t["sent_at"])
    return out


@restaurant_required("kitchen")
def kitchen(request):
    r = request.restaurant
    station = request.GET.get("station", "")
    status = request.GET.get("status", "")
    tickets = _tickets(r, station)
    counts = {s: sum(1 for t in tickets if t["status"] == s) for s in ("new", "preparing", "ready")}
    if status in RANK:
        tickets = [t for t in tickets if t["status"] == status]
    stations = sorted({s for s in r.menu_items.exclude(station="").values_list("station", flat=True)})
    ctx = {"tickets": tickets, "counts": counts, "station": station, "status": status, "stations": stations}
    if request.GET.get("partial"):
        return render(request, "restaurant/partials/kitchen_grid.html", ctx)
    return render(request, "restaurant/kitchen.html", ctx)


@restaurant_required("kitchen")
@require_POST
def kitchen_advance(request, pk, kot_no):
    order = get_order(request, pk)
    station = request.POST.get("station", "")
    items = order.items.filter(kot_no=kot_no, kot_status__in=list(RANK))
    if station:
        items = items.filter(station__iexact=station)
    action = request.POST.get("action", "advance")
    now = timezone.now()
    if action == "cancel":
        n = items.update(kot_status="cancelled", status_changed_at=now)
        order.recalc()
        log_activity(request, "KOT cancelled in kitchen", f"#{order.number} KOT {kot_no}")
    else:
        statuses = list(items.values_list("kot_status", flat=True))
        if statuses:
            lowest = min(statuses, key=lambda s: RANK[s])
            items.filter(kot_status=lowest).update(kot_status=FLOW[lowest], status_changed_at=now)
    sync_order_status_from_items(order)
    if request.headers.get("x-requested-with") == "fetch":
        return HttpResponse("ok")
    nxt = request.POST.get("next", "")
    if nxt.startswith("/app/kitchen/"):
        return redirect(nxt)
    return redirect("restaurant:kitchen")
