import json

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import User
from checkout.models import ProductOrder, BookingOrderItem
import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone

from .forms import RegisterForm
from checkout.models import ProductOrder, BookingOrderItem


@csrf_exempt
def login_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    # 1. Cek Data: Ambil dari request.POST jika ada (dari pbp_django_auth.login())
    if request.POST:
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
    else:
        # 2. Fallback: Jika tidak ada di request.POST, coba parsing dari JSON body
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON or Empty Body"}, status=400)
        
        username = body.get("username", "").strip()
        password = body.get("password", "")

    if not username or not password:
        return JsonResponse({"detail": "Username and password required"}, status=400)

    # Lanjutkan dengan autentikasi menggunakan data yang sudah diparsing
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid credentials"}, status=400) # Ganti status ke 400
    
    # Session dibuat
    login(request, user)

    return JsonResponse({
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": getattr(user, "phone", "") or "",
            "profile_picture": getattr(user, "profile_picture", "") or "",
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser
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
            "profile_picture": getattr(request.user, "profile_picture", "") or "",
        },
        "orders": product_orders,
        "bookings": bookings,
    })

@csrf_exempt
def register_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    form = RegisterForm(body)
    if form.is_valid():
        user = form.save()

        login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])

        return JsonResponse({
            "ok": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "phone": getattr(user, "phone", "") or "",
            }
        }, status=201)

    return JsonResponse({
        "ok": False,
        "errors": form.errors,
    }, status=400)

@csrf_exempt
def logout_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    logout(request)
    return JsonResponse({"ok": True, "detail": "Logged out"})

@csrf_exempt
@login_required
def update_profile_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    try:
        data = json.loads(request.body)
        user = request.user
        
        if 'username' in data and data['username']:
            user.username = data['username']
        
        if 'phone' in data:
            user.phone = data['phone']

        if 'profile_picture' in data:
            user.profile_picture = data['profile_picture']
            
        user.save()
        
        return JsonResponse({
            "ok": True,
            "message": "Profile updated successfully",
            "user": {
                "username": user.username,
                "phone": getattr(user, "phone", "")
            }
        })
    except Exception as e:
        return JsonResponse({"ok": False, "detail": str(e)}, status=400)