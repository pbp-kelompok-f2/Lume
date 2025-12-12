from django.urls import path
from . import views, api

app_name = "checkout"

urlpatterns = [
    # ======================================
    # HTML Views (untuk website)
    # ======================================
    path("cart/", views.cart_checkout_page, name="cart_checkout_page"),
    path("cart/create/", views.checkout_cart_create, name="checkout_cart_create"),
    path("cart/summary/", views.cart_summary_json, name="cart_summary_json"),

    path("booking/<int:booking_id>/", views.booking_checkout, name="booking_checkout"),

    path("confirmed/", views.order_confirmed, name="order_confirmed"),

    # ======================================
    # API Endpoints (untuk Flutter)
    # ======================================
    path("api/cart-summary/", api.cart_summary_api, name="cart_summary_api"),
    path("api/cart-checkout/", api.cart_checkout_api, name="cart_checkout_api"),
    path("api/booking-checkout/<int:booking_id>/", api.booking_checkout_api,name="booking_checkout_api"),
    path("api/history/", api.order_history_json, name="order_history_json"),
    path('api/booking-details/<int:booking_id>/', views.booking_details_api, name='booking_details_api'),
    path('api/process-payment/', views.process_booking_payment_api, name='process_booking_payment_api'),
]
