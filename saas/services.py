"""Onboarding helpers shared by self sign-up and the Super Admin panel."""
import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Plan, PlatformSettings, Subscription

User = get_user_model()


def unique_username(seed):
    base = re.sub(r"[^a-z0-9_.]", "", (seed or "user").lower().replace(" ", "."))[:24] or "user"
    name, n = base, 2
    while User.objects.filter(username=name).exists():
        name, n = f"{base}{n}", n + 1
    return name


def bootstrap_restaurant(restaurant):
    """Give a new restaurant a dining area, tables and starter categories."""
    from restaurant.models import Area, Category, Table

    if not restaurant.areas.exists():
        area = Area.objects.create(restaurant=restaurant, name="Main dining")
        for i in range(1, 9):
            Table.objects.create(restaurant=restaurant, area=area, name=f"T{i}", seats=4, sort_order=i)
    if not restaurant.categories.exists():
        for i, name in enumerate(["Starters", "Main course", "Breads", "Beverages", "Desserts"]):
            Category.objects.create(restaurant=restaurant, name=name, sort_order=i)


@transaction.atomic
def onboard_restaurant(*, name, owner_name, phone, email, password, plan=None, status="trial",
                       cycle="monthly", trial_days=None, business_type="restaurant", city="",
                       access_granted=True):
    from restaurant.models import Restaurant

    ps = PlatformSettings.load()
    if plan is None:
        plan = Plan.objects.filter(is_active=True, is_popular=True).first() or Plan.objects.filter(is_active=True).first()
    if plan is None:
        raise ValueError("Create at least one plan before onboarding restaurants.")

    restaurant = Restaurant.objects.create(
        name=name, phone=phone or "", email=email or "", business_type=business_type, city=city,
        access_granted=access_granted,
    )
    first, _, last = (owner_name or "").strip().partition(" ")
    owner = User(
        username=unique_username(email.split("@")[0] if email else phone or name),
        first_name=first, last_name=last, email=email or "", phone=phone or None,
        role="owner", restaurant=restaurant,
    )
    owner.set_password(password)
    owner.save()

    sub = Subscription(restaurant=restaurant, plan=plan, current_period_end=timezone.now())
    if status == "active":
        sub.status = "trial"
        sub.activate(cycle)
    else:
        sub.start_trial(trial_days if trial_days is not None else (plan.trial_days or ps.default_trial_days))
    sub.save()
    bootstrap_restaurant(restaurant)
    return restaurant, owner
