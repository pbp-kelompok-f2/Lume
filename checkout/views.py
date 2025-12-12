from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from .forms import CartCheckoutForm
from .models import ProductOrder, ProductOrderItem, BookingOrder, BookingOrderItem
from cart.models import Cart
from bookingkelas.models import Booking, ClassSessions
from django.db.models import F
from django.views.decorators.csrf import csrf_exempt
import json


@login_required(login_url="/user/login/")
def cart_checkout_page(request):
    cart = get_object_or_404(
        Cart.objects.prefetch_related("items__product"),
        user=request.user
    )

    items_qs = cart.items.select_related("product").filter(is_selected=True)
    items = list(items_qs)

    if not items:
        messages.error(request, "Pilih dulu item yang mau di-checkout.")
        return redirect("cart:page")

    subtotal = sum(ci.product.price * ci.quantity for ci in items)
    shipping = ProductOrder.FLAT_SHIPPING if items else Decimal("0")
    total = subtotal + shipping

    for ci in items:
        ci.display_name = getattr(ci.product, "product_name",
                            getattr(ci.product, "name", str(ci.product)))
        ci.line_total = ci.product.price * ci.quantity

    items_count = sum(ci.quantity for ci in items)

    form = CartCheckoutForm()
    return render(request, "checkout/cart_checkout_page.html", {
        "form": form,
        "cart_items": items,
        "subtotal": subtotal,
        "shipping": shipping,
        "total": total,
        "items_count": items_count,    
        "payment_method": "Cash on Delivery",
    })

@login_required(login_url="/user/login/")
def checkout_cart_create(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")

    form = CartCheckoutForm(request.POST)
    if not form.is_valid():
        for err in form.errors.values():
            messages.error(request, err)
        return redirect("checkout:cart_checkout_page")

    cart = get_object_or_404(
        Cart.objects.prefetch_related("items__product"),
        user=request.user
    )

    selected_qs = cart.items.select_related("product").filter(is_selected=True)
    if not selected_qs.exists():
        messages.error(request, "Tidak ada item yang dipilih untuk checkout.")
        return redirect("cart:page")

    user = request.user
    receiver_name = user.get_full_name() or user.username
    receiver_phone = getattr(user, "phone", "") or ""
    cd = form.cleaned_data

    with transaction.atomic():
        locked = {}
        for ci in selected_qs.select_related("product"):
            PModel = type(ci.product)
            p = PModel.objects.select_for_update().get(pk=ci.product_id)
            locked[ci.product_id] = p

            if hasattr(p, "stock") and p.stock is not None:
                if p.stock < ci.quantity:
                    messages.error(request, f"Stok {getattr(p, 'name', getattr(p, 'product_name', 'produk'))} tidak mencukupi.")
                    return redirect("cart:page")

        order = ProductOrder.objects.create(
            user=user,
            cart=cart,
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            address_line1=cd["address_line1"],
            address_line2=cd.get("address_line2", ""),
            city=cd["city"],
            province=cd["province"],
            postal_code=cd["postal_code"],
            country=cd["country"],
            notes=cd.get("notes", ""),
        )

        for ci in selected_qs:
            p = locked.get(ci.product_id, ci.product)

            ProductOrderItem.objects.create(
                order=order,
                product=ci.product,
                product_name=getattr(ci.product, "product_name", getattr(ci.product, "name", str(ci.product))),
                unit_price=ci.product.price,
                quantity=ci.quantity,
            )

            if hasattr(p, "stock") and p.stock is not None:
                PModel = type(p)
                PModel.objects.filter(pk=p.pk).update(stock=F("stock") - ci.quantity)

        for p in locked.values():
            if hasattr(p, "inStock"):
                p.refresh_from_db(fields=["stock"])
                if p.stock is not None and p.stock <= 0 and getattr(p, "inStock", True):
                    type(p).objects.filter(pk=p.pk).update(inStock=False)

        order.recalc_totals()
        order.save(update_fields=["subtotal", "shipping_fee", "total"])

        selected_ids = list(selected_qs.values_list("id", flat=True))
        transaction.on_commit(lambda: cart.items.filter(id__in=selected_ids).delete())

    return redirect("checkout:order_confirmed")

def _weekday_map():
    return {
        'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday',
        'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday', 'Sun': 'Sunday'
    }


@login_required(login_url="/user/login/")
def booking_checkout(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("session"),
        id=booking_id, user=request.user, is_cancelled=False
    )

    if BookingOrderItem.objects.filter(booking=booking).exists():
        messages.info(request, "Booking ini sudah pernah di-checkout.")
        return redirect("checkout:order_confirmed")

    if request.method == "POST":
        
        with transaction.atomic():
            session_to_book = ClassSessions.objects.select_for_update().get(id=booking.session.id)
            
            confirmed_count = session_to_book.bookings.filter(
                is_cancelled=False,
                order_items__isnull=False
            ).count()

            if confirmed_count >= session_to_book.capacity_max:
                messages.error(request, "Maaf, kelas sudah penuh saat Anda checkout.")
                booking.delete() 
                return redirect("bookingkelas:catalog")
            
            
            order = BookingOrder.objects.create(user=request.user, notes="") 
            
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
            
            session_to_book.capacity_current = session_to_book.bookings.filter(
                is_cancelled=False, 
                order_items__isnull=False
            ).count()
            session_to_book.save(update_fields=["capacity_current"])
            
            order.recalc_totals() 
            order.save(update_fields=["subtotal", "total"])

            weekday_map = _weekday_map() 
            day_label_success = weekday_map.get(booking.day_selected, booking.day_selected)        
        return redirect("checkout:order_confirmed")

    subtotal = booking.price_at_booking
    shipping = 0 
    total = subtotal + shipping

    context = {
        'booking': booking,
        'subtotal': subtotal,
        'shipping': shipping,
        'total': total,
    }
    return render(request, "checkout/booking_checkout.html", context)


@login_required(login_url="/user/login/")
def cart_summary_json(request):
    cart = get_object_or_404(Cart.objects.prefetch_related("items__product"), user=request.user)

    qs = cart.items.select_related("product")
    if request.GET.get("selected") == "1":
        qs = qs.filter(is_selected=True)

    items = list(qs)
    subtotal = sum(ci.product.price * ci.quantity for ci in items)
    shipping = ProductOrder.FLAT_SHIPPING if items else Decimal("0")
    total = subtotal + shipping
    return JsonResponse({
        "subtotal": float(subtotal),
        "shipping": float(shipping),
        "total": float(total),
        "count": sum(ci.quantity for ci in items),
    })

@login_required(login_url="/user/login/")
def order_confirmed(request):
    return render(request, "checkout/order_confirmed.html")

@login_required
def booking_details_api(request, booking_id):
    """
    API untuk menampilkan detail harga sebelum user klik 'Confirm Payment'.
    Dipanggil saat user masuk ke halaman checkout kelas.
    """
    try:
        # Ambil booking milik user yang sedang login
        booking = Booking.objects.get(id=booking_id, user=request.user)
        
        data = {
            "title": booking.session.title,
            "instructor": booking.session.instructor,
            "time": booking.session.time,
            "day": booking.day_selected, # Hari yang dipilih (misal: Monday)
            "price": booking.price_at_booking,
            "total_payment": booking.price_at_booking, # Tambahkan pajak/admin fee disini jika ada
        }
        return JsonResponse({"status": "success", "data": data})
    except Booking.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Booking not found"}, status=404)

@csrf_exempt
@login_required
def process_booking_payment_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            booking_id = data.get('booking_id')
            
            # 1. Ambil Booking
            booking = Booking.objects.get(id=booking_id, user=request.user)
            
            # 2. Cek apakah sudah dibayar (Cek di BookingOrderItem)
            if BookingOrderItem.objects.filter(booking=booking).exists():
                return JsonResponse({"status": "error", "message": "Booking already paid"}, status=400)

            # 3. BUAT BOOKING ORDER (Induk)
            # Karena BookingOrder butuh total/subtotal, kita isi dengan harga booking
            new_order = BookingOrder.objects.create(
                user=request.user,
                subtotal=booking.price_at_booking,
                total=booking.price_at_booking,
                notes="Booked via Mobile App"
            )

            # 4. BUAT BOOKING ORDER ITEM (Anak)
            # Model Anda mewajibkan session_title dan unit_price
            BookingOrderItem.objects.create(
                order=new_order,
                booking=booking,
                session_title=booking.session.title, # Wajib diisi sesuai model
                unit_price=booking.price_at_booking, # Wajib diisi sesuai model
                quantity=1
            )
            
            return JsonResponse({"status": "success", "message": "Payment successful!"})

        except Booking.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Booking not found"}, status=404)
        except Exception as e:
            print(f"ERROR CHECKOUT: {e}") # Cek terminal kalau masih error
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
            
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=401)