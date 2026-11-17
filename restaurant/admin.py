from django.contrib import admin

from . import models


class OrderItemInline(admin.TabularInline):
    model = models.OrderItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = models.Payment
    extra = 0


@admin.register(models.Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "phone", "is_active", "access_granted", "created_at")
    search_fields = ("name", "city", "phone")
    list_filter = ("is_active", "access_granted", "business_type")


@admin.register(models.Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "restaurant", "order_type", "source", "status", "payment_status", "total", "created_at")
    list_filter = ("restaurant", "status", "source", "order_type")
    inlines = [OrderItemInline, PaymentInline]


@admin.register(models.MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "restaurant", "category", "price", "food_type", "is_available")
    list_filter = ("restaurant", "food_type", "is_available")
    search_fields = ("name",)


for m in (models.Category, models.Area, models.Table, models.Customer, models.InventoryItem,
          models.StockMovement, models.Coupon, models.Device, models.RolePermission, models.WaiterCall):
    admin.site.register(m)
