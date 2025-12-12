from django.urls import path
from . import views, api

app_name = "useradmin"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),

    path("api/stats/", api.api_stats, name="api_stats"),
    path("api/users/", api.api_users, name="api_users"),
    path("api/orders/", api.api_orders, name="api_orders"),
    path("api/bookings/", api.api_bookings, name="api_bookings"),
    path("api/activity/", api.api_activity, name="api_activity"),
    path("api/dashboard-stats/", api.admin_dashboard_stats, name="admin_dashboard_stats"),
]
