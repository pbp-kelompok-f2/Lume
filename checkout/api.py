# checkout/api.py

from decimal import Decimal
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from cart.models import Cart
from bookingkelas.models import Booking, ClassSessions
from .models import (
    ProductOrder,
    ProductOrderItem,
    BookingOrder,
    BookingOrderItem,
)


# ==========================
# Helpers API
# ==========================

def _get_request_data(request):
    """
    Helper supaya endpoint bisa menerima:
    - JSON body (application/json) -> Flutter http.post
    - atau form-encoded (request.POST) -> kalau pakai form biasa
    """
    content_type = (request.content_type or "").split(";")[0].strip()
    if content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8"))
        except Exception:
            return {}
    return request.POST


def _serialize_cart_item(ci):
    """
    Ubah satu CartItem menjadi dict JSON-friendly.
    """
    product_name = getattr(
        ci.product, "product_name",
        getattr(ci.product, "name", str(ci.product))
    )
    return {
        "id": ci.id,
        "product_id": ci.product_id,
        "product_name": product_name,
        "unit_price": float(ci.product.price),
        "quantity": ci.quantity,
        "line_total": float(ci.product.price * ci.quantity),
    }


# ==========================
# A. CART SUMMARY API
# ==========================

@login_required(login_url="/user/login/")
def cart_summary_api(request):
    """
    GET /checkout/api/cart-summary/

    Optional query:
      ?selected=1  -> hanya item yang is_selected=True

    Response JSON:
    {
      "items": [
        {
          "id": ...,
          "product_id": ...,
          "product_name": "...",
          "unit_price": ...,
          "quantity": ...,
          "line_total": ...
        },
        ...
      ],
      "subtotal": ...,
      "shipping": ...,
      "total": ...,
      "count": ...
    }
    """
    if request.method != "GET":
        return HttpResponseBadRequest("GET required.")

    cart = get_object_or_404(
        Cart.objects.prefetch_related("items__product"),
        user=request.user
    )

    qs = cart.items.select_related("product")
    if request.GET.get("selected") == "1":
        qs = qs.filter(is_selected=True)

    items = list(qs)
    subtotal = sum(ci.product.price * ci.quantity for ci in items)
    shipping = ProductOrder.FLAT_SHIPPING if items else Decimal("0")
    total = subtotal + shipping

    return JsonResponse({
        "items": [_serialize_cart_item(ci) for ci in items],
        "subtotal": float(subtotal),
        "shipping": float(shipping),
        "total": float(total),
        "count": sum(ci.quantity for ci in items),
    })


# ==========================
# B. CART CHECKOUT API
# ==========================

@csrf_exempt
@login_required(login_url="/user/login/")
def cart_checkout_api(request):
    """
    POST /checkout/api/cart-checkout/

    Dipanggil Flutter ketika user menekan tombol "Checkout".

    Body (JSON atau form):
      - address_line1 (required)
      - city (required)
      - province (required)
      - postal_code (required)
      - country (required)
      - address_line2 (opsional)
      - notes (opsional)

    Response sukses:
    {
      "success": true,
      "message": "Checkout berhasil.",
      "order_id": 123,
      "subtotal": ...,
      "shipping": ...,
      "total": ...
    }

    Response gagal:
    {
      "success": false,
      "message": "..."
    }
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")

    data = _get_request_data(request)

    required_fields = ["address_line1", "city", "province", "postal_code", "country"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return JsonResponse(
            {
                "success": False,
                "message": f"Field wajib belum lengkap: {', '.join(missing)}",
            },
            status=400,
        )

    cart = get_object_or_404(
        Cart.objects.prefetch_related("items__product"),
        user=request.user
    )

    # Ambil hanya item yang is_selected=True (sama seperti di checkout_cart_create)
    selected_qs = cart.items.select_related("product").filter(is_selected=True)
    if not selected_qs.exists():
        return JsonResponse(
            {
                "success": False,
                "message": "Tidak ada item yang dipilih untuk checkout.",
            },
            status=400,
        )

    user = request.user
    receiver_name = user.get_full_name() or user.username
    receiver_phone = getattr(user, "phone", "") or ""

    with transaction.atomic():
        # 1. Kunci stok product yang terlibat
        locked = {}
        for ci in selected_qs.select_related("product"):
            PModel = type(ci.product)
            p = PModel.objects.select_for_update().get(pk=ci.product_id)
            locked[ci.product_id] = p

            if hasattr(p, "stock") and p.stock is not None:
                if p.stock < ci.quantity:
                    product_name = getattr(
                        p, "name", getattr(p, "product_name", "produk")
                    )
                    return JsonResponse(
                        {
                            "success": False,
                            "message": f"Stok {product_name} tidak mencukupi.",
                        },
                        status=400,
                    )

        # 2. Buat ProductOrder (tanpa form, langsung dari data)
        order = ProductOrder.objects.create(
            user=user,
            cart=cart,
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            address_line1=data.get("address_line1", ""),
            address_line2=data.get("address_line2", ""),
            city=data.get("city", ""),
            province=data.get("province", ""),
            postal_code=data.get("postal_code", ""),
            country=data.get("country", ""),
            notes=data.get("notes", ""),
        )

        # 3. Buat ProductOrderItem + update stok
        for ci in selected_qs:
            p = locked.get(ci.product_id, ci.product)

            ProductOrderItem.objects.create(
                order=order,
                product=ci.product,
                product_name=getattr(
                    ci.product, "product_name",
                    getattr(ci.product, "name", str(ci.product))
                ),
                unit_price=ci.product.price,
                quantity=ci.quantity,
            )

            if hasattr(p, "stock") and p.stock is not None:
                PModel = type(p)
                PModel.objects.filter(pk=p.pk).update(
                    stock=F("stock") - ci.quantity
                )

        # 4. Update inStock jika stok habis
        for p in locked.values():
            if hasattr(p, "inStock"):
                p.refresh_from_db(fields=["stock"])
                if p.stock is not None and p.stock <= 0 and getattr(p, "inStock", True):
                    type(p).objects.filter(pk=p.pk).update(inStock=False)

        # 5. Hitung ulang subtotal, shipping, total
        order.recalc_totals()
        order.save(update_fields=["subtotal", "shipping_fee", "total"])

        # 6. Hapus item yang sudah di-checkout dari cart
        selected_ids = list(selected_qs.values_list("id", flat=True))
        transaction.on_commit(
            lambda: cart.items.filter(id__in=selected_ids).delete()
        )

    return JsonResponse(
        {
            "success": True,
            "message": "Checkout berhasil.",
            "order_id": order.id,
            "subtotal": float(order.subtotal),
            "shipping": float(order.shipping_fee),
            "total": float(order.total),
        }
    )


# ==========================
# C. BOOKING CHECKOUT API
# ==========================

@csrf_exempt
@login_required(login_url="/user/login/")
def booking_checkout_api(request, booking_id):
    """
    POST /checkout/api/booking-checkout/<booking_id>/

    Dipanggil Flutter ketika user confirm booking kelas.

    Response sukses:
    {
      "success": true,
      "message": "Checkout kelas berhasil.",
      "order_id": ...,
      "subtotal": ...,
      "total": ...
    }

    Response gagal:
    {
      "success": false,
      "message": "..."
      "order_id": (optional, kalau sudah pernah di-checkout)
    }
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")

    booking = get_object_or_404(
        Booking.objects.select_related("session"),
        id=booking_id,
        user=request.user,
        is_cancelled=False,
    )

    # Kalau booking ini sudah ada di BookingOrderItem, jangan double checkout
    if BookingOrderItem.objects.filter(booking=booking).exists():
        last_item = (
            BookingOrderItem.objects.filter(booking=booking)
            .select_related("order")
            .order_by("-id")
            .first()
        )
        order_id = last_item.order.id if last_item else None
        return JsonResponse(
            {
                "success": False,
                "message": "Booking ini sudah pernah di-checkout.",
                "order_id": order_id,
            },
            status=400,
        )

    with transaction.atomic():
        # Kunci session agar pengecekan kapasitas aman (race condition)
        session_to_book = ClassSessions.objects.select_for_update().get(
            id=booking.session.id
        )

        confirmed_count = session_to_book.bookings.filter(
            is_cancelled=False,
            order_items__isnull=False,
        ).count()

        if confirmed_count >= session_to_book.capacity_max:
            booking.delete()
            return JsonResponse(
                {
                    "success": False,
                    "message": "Maaf, kelas sudah penuh saat Anda checkout.",
                },
                status=400,
            )

        # Buat BookingOrder
        order = BookingOrder.objects.create(
            user=request.user,
            notes="",  # Bisa nanti ditambah field notes dari Flutter kalau mau
        )

        # Title kelas (kalau ada day_selected, disisipkan)
        title = booking.session.title
        if getattr(booking, "day_selected", ""):
            title = f"{title} ({booking.day_selected})"

        BookingOrderItem.objects.create(
            order=order,
            booking=booking,
            session_title=title,
            occurrence_date=None,
            occurrence_start_time=None,
            unit_price=booking.price_at_booking,
            quantity=1,
        )

        # Update kapasitas current kelas
        session_to_book.capacity_current = session_to_book.bookings.filter(
            is_cancelled=False,
            order_items__isnull=False,
        ).count()
        session_to_book.save(update_fields=["capacity_current"])

        order.recalc_totals()
        order.save(update_fields=["subtotal", "total"])

    return JsonResponse(
        {
            "success": True,
            "message": "Checkout kelas berhasil.",
            "order_id": order.id,
            "subtotal": float(order.subtotal),
            "total": float(order.total),
        }
    )

@csrf_exempt
@login_required(login_url="/user/login/")
def order_history_json(request):
    # Ambil history order user
    orders = ProductOrder.objects.filter(user=request.user).order_by('-created_at')
    
    data = []
    for order in orders:
        items_data = []
        
        # Di sini kita pakai select_related('product') untuk efisiensi
        for item in order.items.select_related('product'):
            img_url = ""
            
            # LOGIKA PENTING: Ambil gambar dari Product asli via ForeignKey
            if item.product:
                # Cek apakah model Product punya 'proxied_thumbnail' (dari file catalog/models.py Anda)
                if hasattr(item.product, 'proxied_thumbnail'):
                    img_url = item.product.proxied_thumbnail
                # Fallback ke field thumbnail biasa
                elif item.product.thumbnail:
                    img_url = item.product.thumbnail
            
            # Jika produk sudah dihapus (item.product is None), gambar akan kosong string ""
            
            items_data.append({
                "name": item.product_name,
                "price": float(item.unit_price),
                "quantity": item.quantity,
                "image": img_url  # <--- Ini kuncinya, kirim URL ke Flutter
            })

        # Set default status jika field tidak ada
        status = getattr(order, 'status', 'Completed')
        
        data.append({
            "id": str(order.id),
            "date_ordered": order.created_at.strftime("%Y-%m-%d"),
            "status": status,
            "total_amount": float(order.total),
            "items": items_data
        })
    
    return JsonResponse(data, safe=False)
