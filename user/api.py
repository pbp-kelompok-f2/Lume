import json

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import User
from checkout.models import ProductOrder, BookingOrderItem


@csrf_exempt
def login_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        return JsonResponse({"detail": "Username and password required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid credentials"}, status=400)

    login(request, user)

    return JsonResponse({
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": getattr(user, "phone", "") or "",
        }
    })


@login_required
def profile_api(request):
    user = request.user

    po_qs = (
        ProductOrder.objects.filter(user=user)
        .prefetch_related("items")
        .order_by("-created_at")
    )

    product_orders = []
    for o in po_qs:
        line_items = []
        for it in o.items.all():
            price = getattr(it, "price", None)
            if price is None:
                price = getattr(it, "unit_price", 0)

            qty = int(getattr(it, "quantity", 0) or 0)

            line_total = getattr(it, "line_total", None)
            if line_total is not None:
                subtotal = int(line_total)
            else:
                try:
                    subtotal = int(qty * float(price))
                except Exception:
                    subtotal = 0

            name = getattr(it, "product_name", None)
            if not name and getattr(it, "product", None):
                name = getattr(it.product, "product_name", "-")

            line_items.append({
                "name": name or "-",
                "qty": qty,
                "price": int(float(price) if price is not None else 0),
                "subtotal": subtotal,
            })

        product_orders.append({
            "id": o.id,
            "created_at": o.created_at.isoformat(),
            "total": int(float(o.total) if o.total is not None else 0),
            "line_items": line_items,
        })

    product_orders.sort(key=lambda x: x["created_at"], reverse=True)

    boi_qs = (
        BookingOrderItem.objects
        .filter(order__user=user)
        .select_related("booking", "order")
        .order_by("-order__created_at", "-id")
    )

    now = timezone.localtime()
    bookings = []
    for it in boi_qs:
        status = "Upcoming"
        if it.occurrence_date and it.occurrence_date < now.date():
            status = "Completed"

        bookings.append({
            "session_title": it.session_title,
            "instructor": getattr(it.booking.session, "instructor", None)
            if hasattr(it.booking, "session") else None,
            "date": it.occurrence_date.isoformat() if it.occurrence_date else None,
            "time": it.occurrence_start_time.isoformat() if it.occurrence_start_time else None,
            "status": status,
        })

    return JsonResponse({
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": getattr(user, "phone", "") or "",
            "member_since": user.date_joined.isoformat(),
        },
        "orders": product_orders,
        "bookings": bookings,
    })
