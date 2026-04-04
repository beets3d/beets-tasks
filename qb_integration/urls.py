from django.urls import path
from .auth import (
    login as qb_login,
    callback as qb_callback,
    launch as qb_launch,
    disconnect as qb_disconnect,
)
from .webhook import qb_webhook

urlpatterns = [
    path("login", qb_login, name="qb-login-alias"),
    path("callback", qb_callback, name="qb-callback-alias"),
    path("launch", qb_launch, name="qb-launch-alias"),
    path("disconnect", qb_disconnect, name="qb-disconnect-alias"),
    path("webhook", qb_webhook, name="qb-webhook-alias"),
    path("webhook/", qb_webhook, name="qb-webhook-alias-slash"),
    
    path("quickbooks/login", qb_login, name="quickbooks-login"),
    path("quickbooks/callback", qb_callback, name="quickbooks-callback"),
    path("quickbooks/launch", qb_launch, name="quickbooks-launch"),
    path("quickbooks/disconnect", qb_disconnect, name="quickbooks-disconnect"),
    path("quickbooks/webhook", qb_webhook, name="quickbooks-webhook"),
    path("quickbooks/webhook/", qb_webhook, name="quickbooks-webhook-slash"),
]