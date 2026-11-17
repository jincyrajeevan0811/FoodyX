from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.permissions import restaurant_required
from core.utils import log_activity

from ..forms import CategoryForm, MenuItemForm
from ..models import Category, MenuItem


@restaurant_required("menu")
def menu(request):
    r = request.restaurant
    tab = request.GET.get("tab", "items")
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("cat", "")
    items = MenuItem.objects.filter(restaurant=r).select_related("category")
    if q:
        items = items.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if cat:
        items = items.filter(category_id=cat)
    categories = Category.objects.filter(restaurant=r).annotate(n=Count("items"))
    return render(request, "restaurant/menu.html", {
        "tab": tab, "q": q, "cat": cat, "items": items, "categories": categories,
        "form": MenuItemForm(restaurant=r), "cat_form": CategoryForm(),
        "total": MenuItem.objects.filter(restaurant=r).count(),
        "unavailable": MenuItem.objects.filter(restaurant=r, is_available=False).count(),
    })


@restaurant_required("menu")
def item_edit(request, pk=None):
    r = request.restaurant
    item = get_object_or_404(MenuItem, pk=pk, restaurant=r) if pk else None
    form = MenuItemForm(request.POST or None, instance=item, restaurant=r)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.restaurant = r
        obj.save()
        log_activity(request, "Menu item saved", f"{obj.name} · ₹{obj.price}")
        messages.success(request, f"{obj.name} saved.")
        if request.POST.get("add_another"):
            return redirect("restaurant:item_add")
        return redirect("restaurant:menu")
    return render(request, "restaurant/menu_item_form.html", {"form": form, "item": item})


@restaurant_required("menu")
@require_POST
def item_toggle(request, pk):
    item = get_object_or_404(MenuItem, pk=pk, restaurant=request.restaurant)
    item.is_available = not item.is_available
    item.save(update_fields=["is_available"])
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "available": item.is_available})
    messages.success(request, f"{item.name} is now {'available' if item.is_available else 'unavailable'}.")
    return redirect("restaurant:menu")


@restaurant_required("menu")
@require_POST
def item_delete(request, pk):
    item = get_object_or_404(MenuItem, pk=pk, restaurant=request.restaurant)
    name = item.name
    item.delete()
    log_activity(request, "Menu item deleted", name)
    messages.success(request, f"{name} deleted.")
    return redirect("restaurant:menu")


@restaurant_required("menu")
@require_POST
def items_bulk(request):
    ids = request.POST.getlist("ids")
    action = request.POST.get("action")
    qs = MenuItem.objects.filter(restaurant=request.restaurant, pk__in=ids)
    n = qs.count()
    if not n:
        messages.error(request, "Select at least one item.")
    elif action == "delete":
        qs.delete()
        log_activity(request, "Menu items deleted", f"{n} items")
        messages.success(request, f"{n} items deleted.")
    elif action in ("available", "unavailable"):
        qs.update(is_available=action == "available")
        messages.success(request, f"{n} items marked {action}.")
    return redirect("restaurant:menu")


@restaurant_required("menu")
@require_POST
def items_import(request):
    """Paste one item per line: name, category, price, veg/non_veg."""
    r = request.restaurant
    text = request.POST.get("csv", "")
    created, skipped = 0, []
    cats = {c.name.lower(): c for c in Category.objects.filter(restaurant=r)}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            skipped.append(n)
            continue
        name, cat_name, price = parts[0], parts[1], parts[2]
        food = (parts[3].lower().replace("-", "_").replace(" ", "_") if len(parts) > 3 else "veg")
        if food in ("nonveg", "non_veg", "nv"):
            food = "non_veg"
        elif food not in ("veg", "egg"):
            food = "veg"
        try:
            price_val = Decimal(price.replace("₹", ""))
        except InvalidOperation:
            skipped.append(n)
            continue
        cat = cats.get(cat_name.lower())
        if cat is None and cat_name:
            cat = Category.objects.create(restaurant=r, name=cat_name, sort_order=len(cats))
            cats[cat_name.lower()] = cat
        MenuItem.objects.create(restaurant=r, name=name[:120], category=cat, price=price_val, food_type=food)
        created += 1
    log_activity(request, "Menu imported", f"{created} items")
    msg = f"{created} items imported."
    if skipped:
        msg += f" Skipped line(s): {', '.join(map(str, skipped[:10]))}."
    messages.success(request, msg)
    return redirect("restaurant:menu")


@restaurant_required("menu")
def category_edit(request, pk=None):
    r = request.restaurant
    cat = get_object_or_404(Category, pk=pk, restaurant=r) if pk else None
    form = CategoryForm(request.POST or None, instance=cat)
    if request.method == "POST":
        if request.POST.get("delete") and cat:
            cat.delete()
            messages.success(request, "Category deleted. Its items are now uncategorised.")
            return redirect(reverse("restaurant:menu") + "?tab=categories")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = r
            obj.save()
            messages.success(request, f"Category “{obj.name}” saved.")
            return redirect(reverse("restaurant:menu") + "?tab=categories")
    return render(request, "restaurant/category_form.html", {"form": form, "cat": cat})
