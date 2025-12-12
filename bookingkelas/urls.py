from django.urls import path
from . import views

app_name = "bookingkelas"

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("json/", views.sessions_json, name="sessions_json"),
    path("add/", views.add_session, name="add_session"),
    
    # alur booking
    path("<int:session_id>/book/", views.book_class, name="book_class"),
    path("get-details/<str:base_title>/", views.get_session_details_json, name="get_session_details"),
    path("book-daily-session/", views.book_daily_session, name="book_daily_session"),

    # CRUD 
    path("classes/", views.class_list, name="class_list"),
    path("classes/<int:pk>/edit/", views.class_edit, name="class_edit"),
    path("classes/<int:pk>/delete/", views.class_delete, name="class_delete"),
    path("classes/<int:pk>/get-form/", views.get_edit_form, name="get_edit_form"),

    path("create-flutter/", views.create_session_flutter, name="create_session_flutter"),
    path("edit-flutter/<int:pk>/", views.edit_session_flutter, name="edit_session_flutter"),
    path("delete-flutter/<int:pk>/", views.delete_session_flutter, name="delete_session_flutter"),
    path("book-flutter/", views.book_session_flutter, name="book_session_flutter"),
    path("my-bookings/", views.my_bookings_flutter, name="my_bookings_flutter"),
    path("api/popular/", views.popular_sessions_json, name="popular_sessions_json"),
]

