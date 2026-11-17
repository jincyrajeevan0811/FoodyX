"""Role-based access control shared by the restaurant and platform panels."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render

from .modules import (
    ALL_MODULES,
    DEFAULT_ROLE_MODULES,
    LOCKED_OWNER_MODULES,
    PLAN_FEATURE_CODES,
    PLATFORM_ROLES,
)

# ------------------------------------------------------------- restaurant


def role_modules(restaurant, role):
    """Modules a role may open, before plan limits are applied."""
    from restaurant.models import RolePermission

    perm = RolePermission.objects.filter(restaurant=restaurant, role=role).first()
    if perm is not None:
        mods = set(perm.modules) & ALL_MODULES
    else:
        mods = set(DEFAULT_ROLE_MODULES.get(role, set()))
    if role in ("owner", "admin"):
        mods |= LOCKED_OWNER_MODULES
    return mods


def plan_allows(restaurant, module):
    """Modules that are also plan features need the plan to include them."""
    if module not in PLAN_FEATURE_CODES:
        return True
    return restaurant.has_feature(module)


def user_modules(user):
    """Final set of modules the user can open (role ∩ plan)."""
    if not user.is_authenticated or not user.restaurant_id:
        return set()
    cache = getattr(user, "_fx_modules", None)
    if cache is not None:
        return cache
    restaurant = user.restaurant
    mods = {m for m in role_modules(restaurant, user.role) if plan_allows(restaurant, m)}
    user._fx_modules = mods
    return mods


def restaurant_required(module=None):
    """Guard a restaurant-panel view.

    Checks sign-in, restaurant access granted by the super admin, a live
    subscription, the plan and the role's permissions. Sets
    ``request.restaurant``.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if user.is_platform and not user.restaurant_id:
                return redirect("saas:overview")
            restaurant = user.restaurant
            if restaurant is None:
                return render(request, "errors/blocked.html", {
                    "title": "No restaurant linked",
                    "message": "Your login is not linked to a restaurant yet. Contact your administrator.",
                }, status=403)
            if not restaurant.is_active or not restaurant.access_granted:
                return render(request, "errors/blocked.html", {
                    "title": "Access paused",
                    "message": "Access to this restaurant has been paused by the FoodyX team. "
                               "Please contact support to restore it.",
                }, status=403)
            request.restaurant = restaurant
            sub = getattr(restaurant, "subscription", None)
            if module != "billing" and (sub is None or not sub.is_live):
                if user.role in ("owner", "admin"):
                    messages.warning(request, "Your plan has expired. Choose a plan to keep using FoodyX.")
                    return redirect("restaurant:billing")
                return render(request, "errors/blocked.html", {
                    "title": "Subscription expired",
                    "message": "The restaurant's FoodyX plan has expired. Ask the owner to renew it.",
                }, status=403)
            if module:
                allowed = user_modules(user)
                if module not in allowed:
                    if module in PLAN_FEATURE_CODES and not restaurant.has_feature(module):
                        return render(request, "errors/upgrade.html", {"module": module}, status=403)
                    return render(request, "errors/blocked.html", {
                        "title": "No access",
                        "message": "Your role does not have access to this page. Ask the owner to change it in Staff & Roles.",
                    }, status=403)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def home_url_for(user):
    """Where a user lands after signing in."""
    if user.is_platform and not user.restaurant_id:
        return "saas:overview"
    mods = user_modules(user)
    for code, url in (
        ("dashboard", "restaurant:dashboard"),
        ("pos", "restaurant:pos"),
        ("kitchen", "restaurant:kitchen"),
        ("rider", "restaurant:rider"),
        ("inventory", "restaurant:inventory"),
    ):
        if code in mods:
            return url
    return "restaurant:billing" if user.role in ("owner", "admin") else "restaurant:dashboard"


# --------------------------------------------------------------- platform
PLATFORM_PERMS = {
    "super_admin": {"view", "manage", "team", "settings"},
    "platform_admin": {"view", "manage"},
    "platform_support": {"view"},
}


def platform_can(user, perm):
    if user.is_superuser:
        return True
    return perm in PLATFORM_PERMS.get(user.role, set())


def platform_required(perm="view"):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not (user.is_superuser or user.role in PLATFORM_ROLES):
                return redirect("core:home_redirect")
            if not platform_can(user, perm):
                messages.error(request, "Your platform role cannot do that.")
                return redirect("saas:overview")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
