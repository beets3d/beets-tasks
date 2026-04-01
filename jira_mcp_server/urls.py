from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("mcp_gateway.urls")),
    path("crm/", include("crm.urls")),
]

# Serve static files for admin assets in this API service deployment.
urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
]
