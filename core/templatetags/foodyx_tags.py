from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


def _indian_group(int_str):
    if len(int_str) <= 3:
        return int_str
    last3 = int_str[-3:]
    rest = int_str[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join(groups) + "," + last3


@register.filter
def inr(value, decimals=None):
    """Format a number the Indian way: ₹1,23,456 (decimals only if needed)."""
    try:
        d = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError, TypeError):
        return value
    negative = d < 0
    d = abs(d)
    if decimals is None:
        decimals = 0 if d == d.to_integral_value() else 2
    d = d.quantize(Decimal(1) / (Decimal(10) ** int(decimals))) if int(decimals) else d.quantize(Decimal(1))
    text = f"{d:.{int(decimals)}f}"
    whole, _, frac = text.partition(".")
    out = "₹" + _indian_group(whole) + ("." + frac if frac else "")
    return ("-" if negative else "") + out


@register.filter
def num(value):
    """Indian grouped number without the rupee sign."""
    return inr(value).replace("₹", "")


@register.filter
def has_module(allowed, code):
    return code in (allowed or set())


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def contains(container, item):
    try:
        return item in container
    except TypeError:
        return False


@register.filter
def percent_of(part, whole):
    try:
        whole = float(whole)
        return 0 if whole == 0 else round(float(part) * 100 / whole)
    except (TypeError, ValueError):
        return 0


STATUS_TONES = {
    # order
    "awaiting": "amber", "accepted": "teal", "preparing": "violet", "ready": "green",
    "served": "slate", "out_for_delivery": "blue", "completed": "green", "cancelled": "red", "rejected": "red",
    # kot
    "pending": "slate", "new": "amber",
    # payment
    "unpaid": "red", "partial": "amber", "paid": "green",
    # subscription
    "trial": "violet", "active": "green", "past_due": "amber", "expired": "red",
    # platform payment
    "created": "slate", "failed": "red", "refunded": "slate",
    # table
    "free": "green", "occupied": "amber", "billed": "blue", "reserved": "violet", "cleaning": "slate",
    # delivery
    "unassigned": "slate", "assigned": "amber", "picked": "blue", "delivered": "green",
}


@register.simple_tag
def badge(status, label=None):
    tone = STATUS_TONES.get(str(status), "slate")
    text = label or str(status).replace("_", " ").capitalize()
    return format_html('<span class="badge badge-{}">{}</span>', tone, text)


@register.filter
def food_dot(food_type):
    cls = {"veg": "veg", "non_veg": "nonveg", "egg": "egg"}.get(food_type, "veg")
    return mark_safe(f'<span class="food-dot {cls}" title="{food_type}"></span>')
