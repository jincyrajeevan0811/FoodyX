from django.urls import reverse

from .modules import MODULES
from .permissions import platform_can, user_modules


def foodyx(request):
    from saas.models import PlatformSettings

    ctx = {}
    try:
        ps = PlatformSettings.load()
    except Exception:  # database not migrated yet
        ps = None
    ctx["platform"] = ps
    ctx["site_name"] = ps.site_name if ps else "FoodyX"

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return ctx

    if user.is_platform:
        ctx["can_manage"] = platform_can(user, "manage")
        ctx["can_team"] = platform_can(user, "team")
        ctx["can_settings"] = platform_can(user, "settings")

    if user.restaurant_id:
        allowed = user_modules(user)
        groups = []
        for code, label, icon, group, url_name in MODULES:
            if code not in allowed:
                continue
            if not groups or groups[-1]["name"] != group:
                groups.append({"name": group, "items": []})
            groups[-1]["items"].append({"code": code, "label": label, "icon": icon, "url": reverse(url_name)})
        ctx["nav_groups"] = groups
        ctx["allowed_modules"] = allowed
        restaurant = user.restaurant
        ctx["current_restaurant"] = restaurant
        ctx["subscription"] = getattr(restaurant, "subscription", None)
        try:
            from restaurant.models import Order, WaiterCall

            ctx["awaiting_count"] = Order.objects.filter(restaurant=restaurant, status="awaiting").count()
            ctx["waiter_calls"] = list(
                WaiterCall.objects.filter(restaurant=restaurant, resolved=False).select_related("table")[:8]
            )
        except Exception:
            ctx["awaiting_count"] = 0
            ctx["waiter_calls"] = []
    return ctx
