from django.conf import settings
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path
from mozilla_django_oidc import views as oidc_views


def _root(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("landing")


urlpatterns = [
    path("", _root),
    path("login/", oidc_views.OIDCAuthenticationRequestView.as_view(), name="login"),
    path("oidc/callback/", oidc_views.OIDCAuthenticationCallbackView.as_view(), name="oidc_authentication_callback"),
    path("logout/", oidc_views.OIDCLogoutView.as_view(), name="logout"),
    path("", include("app.urls")),
]

# Local development only: password login for seed_dev_data's demo accounts.
if settings.DEBUG:
    urlpatterns.insert(0, path(
        "dev-login/", auth_views.LoginView.as_view(template_name="app/dev_login.html"), name="dev_login",
    ))
