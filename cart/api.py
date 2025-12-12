# cart/api.py
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction

from .models import Cart, CartItem
from catalog.models import Product
from .views import _selected_qty 

@login_required
@csrf_exempt
def cart_list_flutter(request):
    if request.method != "GET":
        return HttpResponseBadRequest("GET required")

    
    cart, _ = Cart.objects.get_or_create(user=request.user)
    qs = cart.items.select_related("product")

    selected = request.GET.get("selected")
    if selected == "1":
        qs = qs.filter(is_selected=True)
    elif selected == "0":
        qs = qs.filter(is_selected=False)

    items = []
    for it in qs:
        p = it.product
        items.append({
            "id": it.id,
            "product_id": str(p.pk),  # UUID -> string
            "product_name": getattr(p, "product_name", getattr(p, "name", str(p))),
            "price": getattr(p, "price", 0),
            "thumbnail": getattr(p, "thumbnail", "") or getattr(p, "image_url", ""),
            "quantity": it.quantity,
            "is_selected": it.is_selected,
            "subtotal": it.quantity * getattr(p, "price", 0),
        })

    return JsonResponse({
        "ok": True,
        "message": "",
        "total_items": cart.total_items(),
        "selected_count": cart.items.filter(is_selected=True).count(),
        "selected_qty": _selected_qty(cart),
        "items": items,
    })

@csrf_exempt
@transaction.atomic
def add_to_cart_flutter(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    # kalau belum login, balikin JSON, bukan redirect HTML
    if not request.user.is_authenticated:
        return JsonResponse({
            "ok": False,
            "message": "Please log in before adding items to your cart.",
        }, status=200)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:  
        return HttpResponseBadRequest("Invalid JSON")

    product_id = data.get("product_id")
    qty = data.get("quantity", 1)

    if not product_id:
        return HttpResponseBadRequest("product_id is required")

    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("quantity must be integer")

    if qty <= 0:
        return HttpResponseBadRequest("quantity must be > 0")

    # lock product & cart untuk safety stok
    product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)

    # cek stok
    if product.stock <= 0 or not getattr(product, "inStock", True):
        return JsonResponse({
            "ok": False,
            "message": "Product is out of stock.",
        })

    # kalau item sudah ada, tambahin quantity
    item, created = CartItem.objects.select_for_update().get_or_create(
        cart=cart,
        product=product,
        defaults={"quantity": qty, "is_selected": True},
    )

    if not created:
        new_qty = item.quantity + qty
        if new_qty > product.stock:
            return JsonResponse({
                "ok": False,
                "message": f"Exceeding stock. Only {product.stock} left.",
                "current_quantity": item.quantity,
            })
        item.quantity = new_qty
        item.save(update_fields=["quantity"])

    return JsonResponse({
        "ok": True,
        "message": f"'{getattr(product, 'product_name', str(product))}' added to cart.",
        "cart_count": cart.total_items(),
    })

@login_required
@csrf_exempt
@transaction.atomic
def set_quantity_flutter(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")
    item_id = data.get("item_id")
    qty = data.get("quantity")

    if item_id is None or qty is None:
        return HttpResponseBadRequest("item_id and quantity are required")

    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("quantity must be integer")

    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)
    item = get_object_or_404(
        CartItem.objects.select_for_update().select_related("product"),
        pk=item_id,
        cart=cart,
    )
    product = item.product

    # kalo out of stock, hapus row
    if not getattr(product, "inStock", True) or product.stock <= 0:
        item.delete()
        return JsonResponse({
            "ok": False,
            "message": "Product is out of stock.",
            "item_id": item_id,
            "quantity": 0,
            "selected_qty": _selected_qty(cart),
        })

    # kalau qty minta lebih besar dr stok
    if qty > product.stock:
        return JsonResponse({
            "ok": False,
            "message": f"Exceeding stock. Only {product.stock} left.",
            "item_id": item_id,
            "quantity": item.quantity,
            "selected_qty": _selected_qty(cart),
        })

    # kalau qty <= 0 -> remove
    if qty <= 0:
        item.delete()
        return JsonResponse({
            "ok": True,
            "message": "Item removed from cart.",
            "item_id": item_id,
            "quantity": 0,
            "selected_qty": _selected_qty(cart),
        })

    # normal update
    item.quantity = qty
    item.save(update_fields=["quantity"])

    return JsonResponse({
        "ok": True,
        "message": None,
        "item_id": item_id,
        "quantity": qty,
        "selected_qty": _selected_qty(cart),
    })

@login_required
@csrf_exempt
@transaction.atomic
def remove_item_flutter(request):
    
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    item_id = data.get("item_id")
    if item_id is None:
        return HttpResponseBadRequest("item_id is required")

    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    item.delete()

    return JsonResponse({
        "ok": True,
        "message": "Item removed from cart.",
        "item_id": item_id,
        "total_items": cart.total_items(),
        "selected_count": cart.items.filter(is_selected=True).count(),
        "selected_qty": _selected_qty(cart),
    })

@login_required
@csrf_exempt
@transaction.atomic
def clear_cart_flutter(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError: 
        return HttpResponseBadRequest("Invalid JSON")

    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)
    cart.clear()

    return JsonResponse({
        "ok": True,
        "message": "Cart cleared.",
        "total_items": 0,
        "selected_count": 0,
        "selected_qty": 0,
    })

@login_required
@csrf_exempt
@transaction.atomic
def toggle_select_flutter(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    item_id = data.get("item_id")
    is_selected = data.get("is_selected")

    if item_id is None or is_selected is None:
        return HttpResponseBadRequest("item_id and is_selected are required")

    # is_selected di JSON = true/false -> convert ke bool
    if not isinstance(is_selected, bool):
        return HttpResponseBadRequest("is_selected must be boolean")

    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)

    item.is_selected = is_selected
    item.save(update_fields=["is_selected"])

    return JsonResponse({
        "ok": True,
        "message": "Selection updated.",
        "item_id": item_id,
        "is_selected": item.is_selected,
        "selected_count": cart.items.filter(is_selected=True).count(),
        "selected_qty": _selected_qty(cart),
    })

@login_required
@csrf_exempt
@transaction.atomic
def select_all_flutter(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError: 
        return HttpResponseBadRequest("Invalid JSON")

    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)
    cart.items.update(is_selected=True)

    return JsonResponse({
        "ok": True,
        "message": "All items selected.",
        "selected_count": cart.items.filter(is_selected=True).count(),
        "total_items": cart.total_items(),
        "selected_qty": _selected_qty(cart),
    })

@login_required
@csrf_exempt
@transaction.atomic
def unselect_all_flutter(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError: 
        return HttpResponseBadRequest("Invalid JSON")

    cart, _ = Cart.objects.select_for_update().get_or_create(user=request.user)
    cart.items.update(is_selected=False)

    return JsonResponse({
        "ok": True,
        "message": "Selection cleared.",
        "selected_count": 0,
        "total_items": cart.total_items(),
        "selected_qty": 0,
    })
