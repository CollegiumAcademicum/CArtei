"""Test settings: no LDAP, SQLite in-memory, domain models temporarily managed."""
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
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/abfragen/"
LOGOUT_REDIRECT_URL = "/login/"
STATIC_URL = "static/"
STATIC_ROOT = "/tmp/cartei-test-static"
CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"
LDAP_GROUPS_BASE = "cn=groups,dc=test"
LDAP_REQUIRE_GROUP = "cn=clearance,dc=test"
LDAP_USER_SEARCH_BASE = "cn=users,dc=test"
