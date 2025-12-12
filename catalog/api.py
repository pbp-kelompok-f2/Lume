from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from catalog.models import Product
import json
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test

def is_admin(u): return u.is_staff

def serialize_product(p: Product):
    return {
        "id": str(p.id),
        "name": p.product_name,
        "description": p.description,
        "price": p.price,
        "stock": p.stock,
        "in_stock": p.inStock,
        "thumbnail": p.normalized_thumbnail,
        "thumbnail_proxy": p.proxied_thumbnail,
        "external_id": p.external_id,
    }

@require_http_methods(["GET"])
def api_products(request):
    qs = Product.objects.all().order_by("-id")
    q = request.GET.get("q")
    if q:
        qs = qs.filter(product_name__icontains=q)
    limit = int(request.GET.get("limit", 50))
    offset = int(request.GET.get("offset", 0))
    data = [serialize_product(p) for p in qs[offset:offset + limit]]
    return JsonResponse({"count": qs.count(), "results": data})

@require_http_methods(["GET"])
def api_product_detail(request, pk):
    p = get_object_or_404(Product, pk=pk)
    return JsonResponse(serialize_product(p))

@csrf_exempt
@require_http_methods(["POST"])
@login_required
@user_passes_test(is_admin)
def api_product_create(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")
    p = Product.objects.create(
        product_name=body.get("name", ""),
        description=body.get("description", ""),
        price=body.get("price", 0),
        stock=body.get("stock", 0),
        inStock=body.get("in_stock", True),
        thumbnail=body.get("thumbnail", ""),
        external_id=body.get("external_id") or None,
    )
    return JsonResponse(serialize_product(p), status=201)

@csrf_exempt
@require_http_methods(["PUT","PATCH", "POST"])
@login_required
@user_passes_test(is_admin)
def api_product_update(request, pk):
    p = get_object_or_404(Product, pk=pk)
    body = json.loads(request.body or "{}")
    for field, value in {
        "product_name": body.get("name"),
        "description": body.get("description"),
        "price": body.get("price"),
        "stock": body.get("stock"),
        "inStock": body.get("in_stock"),
        "thumbnail": body.get("thumbnail"),
        "external_id": body.get("external_id"),
    }.items():
        if value is not None:
            setattr(p, field, value)
    p.save()
    return JsonResponse(serialize_product(p))

@csrf_exempt
@require_http_methods(["DELETE", "POST"])
@login_required
@user_passes_test(is_admin)
def api_product_delete(request, pk):
    p = get_object_or_404(Product, pk=pk)
    p.delete()
    return JsonResponse({"ok": True})
