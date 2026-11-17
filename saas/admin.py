from django.contrib import admin

from .models import ActivityLog, Plan, PlatformPayment, PlatformSettings, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_monthly", "price_yearly", "is_popular", "is_active", "sort_order")
    list_editable = ("sort_order",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("restaurant", "plan", "status", "billing_cycle", "current_period_end")
    list_filter = ("status", "plan")


@admin.register(PlatformPayment)
class PlatformPaymentAdmin(admin.ModelAdmin):
    list_display = ("restaurant", "plan", "total", "status", "method", "created_at", "invoice_no")
    list_filter = ("status", "method")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "restaurant", "action")
    search_fields = ("action", "detail")


admin.site.register(PlatformSettings)
