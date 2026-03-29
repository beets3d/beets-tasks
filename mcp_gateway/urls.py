from django.urls import path

from .views import healthz, mcp_endpoint

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("mcp", mcp_endpoint, name="mcp-endpoint"),
]
