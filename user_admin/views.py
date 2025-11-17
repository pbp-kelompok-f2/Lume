from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render

def is_admin(u):
    return u.is_staff

@login_required(login_url="/user/login/")
@user_passes_test(is_admin)
def dashboard(request):
    return render(request, "admin_dashboard.html")
