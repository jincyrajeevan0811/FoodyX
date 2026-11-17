import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import Order


def get_order(request, pk):
    return get_object_or_404(Order.objects.select_related("table", "customer", "rider"), pk=pk, restaurant=request.restaurant)


def back(request, fallback, **kwargs):
    """Redirect to ?next= when it is a local URL, else to the fallback view."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback, **kwargs)


def csv_response(filename, rows):
    import csv

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("﻿")  # Excel-friendly BOM
    writer = csv.writer(resp)
    for row in rows:
        writer.writerow(row)
    return resp


def menu_payload(restaurant, online_only=False):
    """Menu as JSON for the POS and the storefront."""
    cats = list(restaurant.categories.filter(is_active=True).values("id", "name"))
    items = restaurant.menu_items.filter(is_available=True).select_related("category")
    if online_only:
        items = items.filter(show_online=True)
    data = [{
        "id": m.id, "name": m.name, "price": float(m.price), "cat": m.category_id, "type": m.food_type,
        "desc": m.description, "img": m.image_url, "featured": m.is_featured, "prep": m.prep_minutes,
    } for m in items]
    return {"categories": cats, "items": data}
