from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path


def _root(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("landing")


urlpatterns = [
    path("", _root),
    path("login/", auth_views.LoginView.as_view(template_name="app/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("app.urls")),
]
