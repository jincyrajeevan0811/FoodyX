from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required
from core.utils import is_local_request, log_activity, public_base_url

from ..forms import AreaForm, TableForm
from ..models import Area, Table


def _table_limit_reached(restaurant):
    plan = restaurant.plan
    return bool(plan and plan.max_tables and restaurant.tables.count() >= plan.max_tables)


@restaurant_required("tables")
def tables(request):
    r = request.restaurant
    areas = Area.objects.filter(restaurant=r).prefetch_related("tables")
    loose = Table.objects.filter(restaurant=r, area__isnull=True)
    return render(request, "restaurant/tables.html", {
        "areas": areas, "loose": loose, "table_form": TableForm(restaurant=r), "area_form": AreaForm(),
        "table_count": r.tables.count(), "limit": r.plan.max_tables if r.plan else 0,
    })


@restaurant_required("tables")
def table_edit(request, pk=None):
    r = request.restaurant
    table = get_object_or_404(Table, pk=pk, restaurant=r) if pk else None
    if table is None and _table_limit_reached(r):
        messages.error(request, f"Your plan allows {r.plan.max_tables} tables. Upgrade to add more.")
        return redirect("restaurant:tables")
    form = TableForm(request.POST or None, instance=table, restaurant=r)
    if request.method == "POST":
        if request.POST.get("delete") and table:
            if table.open_order:
                messages.error(request, "This table has an open order.")
            else:
                table.delete()
                messages.success(request, "Table deleted.")
            return redirect("restaurant:tables")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = r
            obj.save()
            messages.success(request, f"{obj.name} saved.")
            return redirect("restaurant:tables")
    return render(request, "restaurant/table_form.html", {"form": form, "table": table})


@restaurant_required("tables")
@require_POST
def tables_bulk_add(request):
    r = request.restaurant
    area = Area.objects.filter(restaurant=r, pk=request.POST.get("area")).first()
    prefix = (request.POST.get("prefix") or "T").strip()[:10]
    try:
        count = max(1, min(50, int(request.POST.get("count") or 1)))
        seats = max(1, int(request.POST.get("seats") or 4))
    except ValueError:
        count, seats = 1, 4
    existing = set(r.tables.values_list("name", flat=True))
    created, n = 0, 1
    while created < count:
        if _table_limit_reached(r):
            messages.warning(request, "Plan table limit reached.")
            break
        name = f"{prefix}{n}"
        n += 1
        if name in existing:
            continue
        Table.objects.create(restaurant=r, area=area, name=name, seats=seats, sort_order=n)
        created += 1
    log_activity(request, "Tables added", f"{created} tables")
    messages.success(request, f"{created} tables added.")
    return redirect("restaurant:tables")


@restaurant_required("tables")
def area_edit(request, pk=None):
    r = request.restaurant
    area = get_object_or_404(Area, pk=pk, restaurant=r) if pk else None
    if area is None and r.areas.exists() and not r.has_feature("multi_area"):
        messages.error(request, "Multiple areas and hotel rooms need a higher plan.")
        return redirect("restaurant:tables")
    form = AreaForm(request.POST or None, instance=area)
    if request.method == "POST":
        if request.POST.get("delete") and area:
            area.delete()
            messages.success(request, "Area deleted. Its tables are kept without an area.")
            return redirect("restaurant:tables")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = r
            obj.save()
            messages.success(request, f"{obj.name} saved.")
            return redirect("restaurant:tables")
    return render(request, "restaurant/area_form.html", {"form": form, "area": area})


@restaurant_required("tables")
def tables_qr(request):
    r = request.restaurant
    tables = Table.objects.filter(restaurant=r).select_related("area")
    base = public_base_url(request)
    return render(request, "restaurant/tables_qr.html", {
        "tables": tables, "base": base, "local_mode": is_local_request(request),
    })
