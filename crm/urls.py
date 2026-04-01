from django.urls import path
from . import views

urlpatterns = [
    path("map/", views.hk_schools_map, name="crm.hk_schools_map"),
    path("api/schools/", views.hk_schools_api, name="crm.hk_schools_api"),
    path("customers/", views.customers_list, name="crm.customers_list"),
    path("customers/<int:cid>/", views.customer_detail, name="crm.customer_detail"),
]
