"""Test settings: no LDAP/Keycloak, SQLite in-memory, domain models temporarily managed."""
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
SECRET_KEY = "test-secret-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "mozilla_django_oidc.middleware.SessionRefresh",
    "app.middleware.ImpersonationMiddleware",
    "app.middleware.RequiredProfileSetupMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "cartei.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGIN_REDIRECT_URL_FAILURE = "/info/?login=failed"
LOGOUT_REDIRECT_URL = "/"
_oidc = "https://kc.test/realms/test/protocol/openid-connect"
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_oidc}/auth"
OIDC_OP_TOKEN_ENDPOINT = f"{_oidc}/token"
OIDC_OP_USER_ENDPOINT = f"{_oidc}/userinfo"
OIDC_OP_JWKS_ENDPOINT = f"{_oidc}/certs"
OIDC_OP_LOGOUT_ENDPOINT = f"{_oidc}/logout"
OIDC_OP_LOGOUT_URL_METHOD = "app.auth.keycloak_logout_url"
OIDC_RP_CLIENT_ID = "cartei"
OIDC_RP_CLIENT_SECRET = "test"
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_STORE_ID_TOKEN = True
# SessionRefresh (MIDDLEWARE): after this long, the next page load silently
# re-checks with Keycloak, re-syncing groups/clearance; refused -> logged out.
OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS = 15 * 60
STATIC_URL = "static/"
STATIC_ROOT = "/tmp/cartei-test-static"
CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"
CARTEI_IMPERSONATION_GROUP = "cn=cartei_impersonation,dc=test"
LDAP_GROUPS_BASE = "cn=groups,dc=test"
LDAP_REQUIRE_GROUP = "cn=clearance,dc=test"
LDAP_USER_SEARCH_BASE = "cn=users,dc=test"
TENANT_ROLE_GROUPS = {
    "admin": ["admins"],
    "cluster": ["gr.cluster"],
    "belegium": ["gr.belegium"],
    "mietverwaltung": ["ag.mietverwaltung"],
    "mietverwaltung_helfer": ["cartei_helfer_mietverwaltung"],
    "werkstatt": ["cartei_werkstatt"],
    "finanzierung": ["ag.finanzierung"],
}
