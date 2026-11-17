from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class FoodyXUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "phone", "email", "role", "restaurant", "is_active")
    list_filter = ("role", "is_active", "restaurant")
    search_fields = ("username", "first_name", "last_name", "phone", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("FoodyX", {"fields": ("role", "phone", "restaurant", "pin", "is_online")}),
    )
