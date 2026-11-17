from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "FoodyX raw data"
admin.site.site_title = "FoodyX admin"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("platform/", include("saas.urls")),
    path("app/", include("restaurant.urls")),
    path("", include("storefront.urls")),
    path("", include("core.urls")),
]
