from django.http import JsonResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Customer


@require_GET
def hk_schools_api(request):
    qs = Customer.objects.filter(customer_type__key="school")
    items = []
    for c in qs:
        items.append(
            {
                "id": c.id,
                "name": c.name,
                "company_name": c.company_name,
                "email": c.email,
                "attn": c.attn,
                "fax": c.fax,
                "phone": c.phone,
                "lat": float(c.latitude) if c.latitude is not None else None,
                "lng": float(c.longitude) if c.longitude is not None else None,
            }
        )
    return JsonResponse({"count": len(items), "items": items})


@require_GET
def hk_schools_map(request):
    # renders a page with a Leaflet map; the page will fetch /crm/api/schools/
    return render(request, "crm/map.html", {})


@require_GET
def customers_list(request):
    # query params: limit, offset, customerType (id or key), query, important
    limit = max(1, min(int(request.GET.get("limit", 100)), 1000))
    offset = max(0, int(request.GET.get("offset", 0)))
    ctype = request.GET.get("customerType")
    important = request.GET.get("important")
    query = (request.GET.get("query") or "").strip()

    qs = Customer.objects.all()
    if ctype:
        try:
            cid = int(ctype)
        except Exception:
            cid = None
        if cid:
            qs = qs.filter(customer_type__id=cid)
        else:
            qs = qs.filter(customer_type__key=str(ctype))
    if important is not None and important != "":
        qs = qs.filter(important=important.lower() in {"1", "true", "yes", "y", "on"})
    if query:
        from django.db.models import Q

        q = Q(name__icontains=query) | Q(company_name__icontains=query) | Q(email__icontains=query) | Q(external_id__icontains=query)
        qs = qs.filter(q)

    total = qs.count()
    items = []
    for obj in qs.order_by("-updated_at")[offset : offset + limit]:
        items.append(
            {
                "id": obj.id,
                "name": obj.name,
                "external_id": obj.external_id,
                    "website_url": obj.website_url,
                    "street_address": obj.street_address,
                    "city": obj.city,
                    "state": obj.state,
                    "zip_code": obj.zip_code,
                    "country": obj.country,
                    "company_name": obj.company_name,
                "email": obj.email,
                "phone": obj.phone,
                "mobile": obj.mobile,
                "attn_2": obj.attn_2,
                "phone_2": obj.phone_2,
                "email_2": obj.email_2,
                "attn_3": obj.attn_3,
                "phone_3": obj.phone_3,
                "email_3": obj.email_3,
                "important": obj.important,
                "customer_type": (obj.customer_type.key if getattr(obj, "customer_type", None) else None),
                "last_contact": obj.last_contact.isoformat() if obj.last_contact else None,
                "sheet_last_updated": obj.sheet_last_updated.isoformat() if obj.sheet_last_updated else None,
                "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
                "profile": obj.profile,
            }
        )
    return JsonResponse({"total": total, "count": len(items), "items": items})


@require_GET
def customer_detail(request, cid: int):
    obj = Customer.objects.filter(id=cid).first()
    if not obj:
        raise Http404("customer not found")
    return JsonResponse(
        {
            "id": obj.id,
            "name": obj.name,
            "external_id": obj.external_id,
            "company_name": obj.company_name,
            "street_address": obj.street_address,
            "city": obj.city,
            "state": obj.state,
            "country": obj.country,
            "zip_code": obj.zip_code,
            "email": obj.email,
            "website_url": obj.website_url,
                "phone": obj.phone,
                "mobile": obj.mobile,
                "attn": obj.attn,
                "fax": obj.fax,
            "attn_2": obj.attn_2,
            "phone_2": obj.phone_2,
            "email_2": obj.email_2,
            "attn_3": obj.attn_3,
            "phone_3": obj.phone_3,
            "email_3": obj.email_3,
            "remark": obj.remark,
            "profile": obj.profile,
            "important": obj.important,
            "customer_type": (obj.customer_type.key if getattr(obj, "customer_type", None) else None),
            "last_contact": obj.last_contact.isoformat() if obj.last_contact else None,
            "sheet_last_updated": obj.sheet_last_updated.isoformat() if obj.sheet_last_updated else None,
            "sheet_updated_by": obj.sheet_updated_by,
            "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        }
    )
