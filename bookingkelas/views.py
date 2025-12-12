from django.contrib.auth.decorators import login_required, user_passes_test
from .models import ClassSessions, WEEKDAYS, Booking, CATEGORY_CHOICES
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from checkout.models import BookingOrderItem
from django.contrib import messages
from django.db import transaction
from .forms import SessionsForm, AdminSessionsForm, AdminSessionEditForm
from decimal import Decimal
import re
import json
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Q

def admin_check(u): return u.is_staff

def _weekday_map():
    day_map = dict(WEEKDAYS)
    day_map.update({
        '0': 'Monday',
        '1': 'Tuesday',
        '2': 'Wednesday',
        '3': 'Thursday',
        '4': 'Friday',
        '5': 'Saturday',
        '6': 'Sunday',
    })
    return day_map

def _base_title(title):
    return title.rsplit(' - ', 1)[0]

def catalog(request):
    qs = ClassSessions.objects.all().order_by("title")
    weekday_map = _weekday_map()

    add_form = AdminSessionsForm()

    category_filter = request.GET.get("category")
    if category_filter and category_filter != "all":
        qs = qs.filter(category__iexact=category_filter)
    groups = {}
    for s in qs:
        base = _base_title(s.title)
        key = (base, s.time, s.category)

        days = s.days or []
        days_names = [weekday_map.get(str(d), str(d)) for d in days]

        if key not in groups:
            groups[key] = {
                "base_title": base,
                "category": s.category,
                "instructor": s.instructor,
                "time": s.time,
                "room": s.room,
                "price": s.price,
                "capacity_max": s.capacity_max,
                "days_keys": set(days),
                "days_names": set(days_names),
                "instances": [s],
            }
        else:
            groups[key]["instances"].append(s)
            groups[key]["days_keys"].update(days)
            groups[key]["days_names"].update(days_names)

    grouped_sessions = []
    for (base, time, category), info in groups.items():
        inst0 = info["instances"][0]
        grouped_sessions.append({
            "base_title": info["base_title"],
            "category": info["category"],
            "instructor": info["instructor"],
            "time": info["time"],
            "room": info["room"],
            "price": info["price"],
            "capacity_current": inst0.capacity_current,
            "capacity_max": info["capacity_max"],
            "days_keys": sorted(list(info["days_keys"])),
            "days_names": sorted(list(info["days_names"])),
            "instance_id": inst0.id,  
        })
    grouped_sessions = sorted(grouped_sessions, key=lambda x: (x["category"], x["time"], x["base_title"]))

    context = {
        "sessions": grouped_sessions,
        "add_form": add_form, 
    }
    return render(request, "show_class.html", context)

def sessions_json(request):
    qs = ClassSessions.objects.all().order_by("title")
    weekday_map = _weekday_map()
    data = []
    for s in qs:
        days = s.days or []
        data.append({
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "category_display": dict(CATEGORY_CHOICES).get(s.category, s.category),
            "instructor": s.instructor,
            "capacity_current": s.capacity_current,
            "capacity_max": s.capacity_max,
            "description": s.description,
            "price": s.price,
            "room": s.room,
            "days": days,
            "days_names": [weekday_map.get(str(d), str(d)) for d in days],
            "time": s.time,
            "is_full": s.is_full,
        })
    return JsonResponse({"sessions": data})

def get_session_details_json(request, base_title):
    sessions_in_group = ClassSessions.objects.filter(title__startswith=base_title)
    
    if not sessions_in_group.exists():
        return JsonResponse({"error": "Sessions not Found"}, status=404)

    s_general = sessions_in_group.first()
    base_title_cleaned = _base_title(s_general.title)
    weekday_map = _weekday_map()
    day_options = []
    for s_item in sessions_in_group:
        if s_item.days:
            day_key = s_item.days[0].lower().strip()
            day_label = weekday_map.get(day_key, day_key)
            day_options.append({
                "value_id": s_item.id,
                "label": day_label,
                "is_full": s_item.is_full,
                'capacity_current': s_item.capacity_current,
                'capacity_max': s_item.capacity_max,
            })
    data = {
        "base_title_cleaned": base_title_cleaned,
        "instructor": s_general.instructor,
        "time": s_general.time,
        "room": s_general.room,
        "price": s_general.price,
        "description": s_general.description, 
        "day_options": day_options
    }
    return JsonResponse(data)

@login_required(login_url="/user/login/")
@transaction.atomic
def book_class(request, session_id):
    s = get_object_or_404(ClassSessions.objects.select_for_update(), id=session_id)

    if s.is_full:
        messages.error(request, "Class is Full.")
        return redirect("bookingkelas:catalog")

    if Booking.objects.filter(user=request.user, session=s, is_cancelled=False).exists():
        messages.info(request, "You have already booked this class.")
        return redirect("bookingkelas:catalog")

    new_booking = Booking.objects.create(
        user=request.user,
        session=s,
        price_at_booking=Decimal(s.price),
    )
    return redirect("checkout:booking_checkout", booking_id=new_booking.id)

@login_required(login_url="/user/login/")
@transaction.atomic
def book_daily_session(request):
    
    if request.method == "POST":
        selected_session_id = request.POST.get("session_id")
        if not selected_session_id:
            messages.error(request, "Choose one of the available days to proceed.")
            return redirect("bookingkelas:catalog") 
        try:
            s_to_book = get_object_or_404(ClassSessions, id=selected_session_id)
            is_confirmed = Booking.objects.filter(
                user=request.user, 
                session=s_to_book, 
                is_cancelled=False,
                order_items__isnull=False 
            ).exists()

            if is_confirmed:
                messages.info(request, "You have already booked this class.")
                return redirect("bookingkelas:catalog")

            pending_booking = Booking.objects.filter(
                user=request.user, 
                session=s_to_book, 
                is_cancelled=False,
                order_items__isnull=True
            ).first()

            if pending_booking:
                return redirect("checkout:booking_checkout", booking_id=pending_booking.id)
            confirmed_count = s_to_book.bookings.filter(
                is_cancelled=False, 
                order_items__isnull=False
            ).count()
            
            if confirmed_count >= s_to_book.capacity_max:
                 messages.error(request, "Class is Full.")
                 return redirect("bookingkelas:catalog")

            new_booking = Booking.objects.create(
                user=request.user,
                session=s_to_book,
                day_selected=s_to_book.days[0], 
                price_at_booking=Decimal(s_to_book.price),
            )
            return redirect("checkout:booking_checkout", booking_id=new_booking.id)
        
        except ClassSessions.DoesNotExist:
            messages.error(request, "Session invalid")
            return redirect("bookingkelas:catalog")
        except Exception as e:
            messages.error(request, f"Problem while booking{e}")
            return redirect("bookingkelas:catalog")

    return redirect("bookingkelas:catalog")

@login_required
@user_passes_test(admin_check)
def class_list(request):
    classes = ClassSessions.objects.all().order_by("title")
    return render(request, "class_list.html", {"classes": classes})

@login_required
@user_passes_test(admin_check)
def class_edit(request, pk):
    """
    View ini menangani SUBMIT (POST) dari modal Edit.
    """
    kelas = get_object_or_404(ClassSessions, pk=pk)
    form = AdminSessionEditForm(request.POST or None, instance=kelas)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Session successfully updated.")
        return redirect("bookingkelas:class_list")
    return render(request, "edit_form.html", {"form": form})

@login_required
@user_passes_test(admin_check)
def class_delete(request, pk):
    kelas = get_object_or_404(ClassSessions, pk=pk)
    
    if request.method == "POST":
        kelas.delete()
        messages.success(request, "Session successfully deleted.")
        return redirect("bookingkelas:class_list")

    messages.error(request, "Invalid request method.")
    return redirect("bookingkelas:class_list")

@login_required
@user_passes_test(admin_check)
def get_edit_form(request, pk):
    kelas = get_object_or_404(ClassSessions, pk=pk)
    form = AdminSessionEditForm(instance=kelas) 
    return render(request, "edit_form.html", {"form": form, "pk": pk})

@login_required
@user_passes_test(admin_check)
def add_session(request):
    if request.method != "POST":
        return redirect("bookingkelas:catalog") 

    form = AdminSessionsForm(request.POST)
    
    if form.is_valid():
        instance = form.save() 
        messages.success(request, f"Sesi '{instance.title}' berhasil dibuat.")
        return redirect("bookingkelas:catalog")

    else:
        error_str = "Gagal menambah sesi. "
        for field, errors in form.errors.items():
            error_str += f"{field.replace('_', ' ').title()}: {' '.join(errors)} "
        
        messages.error(request, error_str)
        return redirect("bookingkelas:catalog")
    
# ==========================================
# API FOR FLUTTER INTEGRATION
# ==========================================

@csrf_exempt
def create_session_flutter(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Validasi input sederhana
            required_fields = ['title', 'instructor', 'time', 'date', 'category', 'price', 'capacity_max']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({"status": "error", "message": f"Field {field} is required"}, status=400)

            # Mapping weekday dari input (misal "Monday") ke format model (angka '0'-'6')
            # Asumsi flutter mengirim list hari misal ["0", "2"] atau nama hari
            # Sederhananya kita ambil raw data dulu
            
            new_session = ClassSessions.objects.create(
                title=data['title'],
                instructor=data['instructor'],
                time=data['time'],
                days=data.get('days', []), # Pastikan format list string, misal ["0", "2"]
                category=data['category'],
                description=data.get('description', ''),
                price=Decimal(data['price']),
                capacity_max=int(data['capacity_max']),
                room=data.get('room', 'Studio 1'),
            )
            
            return JsonResponse({
                "status": "success", 
                "message": "Class created successfully",
                "id": new_session.id
            }, status=200)

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "error", "message": "Invalid method"}, status=401)

@csrf_exempt
def edit_session_flutter(request, pk):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            session = ClassSessions.objects.get(pk=pk)

            # Update fields if they exist in request
            if 'title' in data: session.title = data['title']
            if 'instructor' in data: session.instructor = data['instructor']
            if 'time' in data: session.time = data['time']
            if 'days' in data: session.days = data['days']
            if 'category' in data: session.category = data['category']
            if 'description' in data: session.description = data['description']
            if 'price' in data: session.price = Decimal(data['price'])
            if 'capacity_max' in data: session.capacity_max = int(data['capacity_max'])
            if 'room' in data: session.room = data['room']
            
            session.save()

            return JsonResponse({"status": "success", "message": "Class updated successfully"}, status=200)
        except ClassSessions.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Class not found"}, status=404)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "error", "message": "Invalid method"}, status=401)

@csrf_exempt
def delete_session_flutter(request, pk):
    if request.method == 'POST':
        try:
            session = ClassSessions.objects.get(pk=pk)
            session.delete()
            return JsonResponse({"status": "success", "message": "Class deleted successfully"}, status=200)
        except ClassSessions.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Class not found"}, status=404)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=401)

@csrf_exempt
@login_required(login_url="/user/login/") 
def book_session_flutter(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            session_id = data.get('session_id')
            
            if not session_id:
                return JsonResponse({"status": "error", "message": "Session ID is required"}, status=400)
                
            s_to_book = ClassSessions.objects.select_for_update().get(id=session_id) # Gunakan select_for_update agar aman dari race condition

            # 1. Cek apakah user sudah booking (Confirmed)
            is_confirmed = Booking.objects.filter(
                user=request.user, 
                session=s_to_book, 
                is_cancelled=False,
                order_items__isnull=False 
            ).exists()

            if is_confirmed:
                return JsonResponse({"status": "error", "message": "You have already booked this class."}, status=400)

            # 2. Cek Kapasitas
            if s_to_book.capacity_current >= s_to_book.capacity_max:
                 return JsonResponse({"status": "error", "message": "Class is Full."}, status=400)

            # 3. Create New Booking
            new_booking = Booking.objects.create(
                user=request.user,
                session=s_to_book,
                day_selected=s_to_book.days[0] if s_to_book.days else "0", 
                price_at_booking=Decimal(s_to_book.price),
            )
            
            # --- TAMBAHKAN INI: UPDATE KAPASITAS ---
            s_to_book.capacity_current += 1
            s_to_book.save()
            # ---------------------------------------
            
            return JsonResponse({
                "status": "success", 
                "message": "Booking created",
                "booking_id": new_booking.id,
                "is_new": True
            }, status=200)

        except ClassSessions.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Session not found"}, status=404)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
            
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=401)

@login_required(login_url="/user/login/")
def my_bookings_flutter(request):
    # Untuk melihat daftar booking user tersebut
    bookings = Booking.objects.filter(user=request.user, is_cancelled=False).order_by('-created_at')
    data = []
    for b in bookings:
        status = "Confirmed" if b.order_items.exists() else "Pending Payment"
        data.append({
            "booking_id": b.id,
            "session_title": b.session.title,
            "instructor": b.session.instructor,
            "time": b.session.time,
            "day": b.day_selected,
            "price": b.price_at_booking,
            "status": status
        })
    return JsonResponse({"bookings": data})


def popular_sessions_json(request):

    qs = (
        ClassSessions.objects
        .annotate(num_bookings=Count("bookings", filter=Q(bookings__is_cancelled=False, bookings__order_items__isnull=False)))
        .filter(num_bookings__gt=0)
        .order_by("-num_bookings", "-id")
    )[:6]

    weekday_map = _weekday_map()
    data = []
    for s in qs:
        days = s.days or []
        data.append({
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "instructor": s.instructor,
            "capacity_current": s.capacity_current,
            "capacity_max": s.capacity_max,
            "price": s.price,
            "room": s.room,
            "days": days,
            "days_names": [weekday_map.get(str(d), str(d)) for d in days],
            "time": s.time,
            "is_full": s.is_full,
            "num_bookings": s.num_bookings,
            "description": s.description,
        })
    return JsonResponse({"sessions": data})
