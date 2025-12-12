from django.urls import path
from . import views, api

app_name = 'user'

urlpatterns = [
    path("register/", views.register_user, name="register"),
    path("login/", views.login_user, name="login"),
    path("logout/", views.logout_user, name="logout"),
    path("profile/", views.my_profile, name="my_profile"),

    path("api/login/", api.login_api, name="api-login"),
    path("api/profile/", api.profile_api, name="api-profile"),
    path("api/register/", api.register_api, name="api-register"),
    path("api/logout/", api.logout_api, name="api-logout"),
    path("api/profile/update/", api.update_profile_api, name="update_profile_api"),
]
