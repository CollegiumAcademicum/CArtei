import os
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

_INSECURE_KEY = "insecure-dev-key-do-not-use-in-production"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _INSECURE_KEY)
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

if not DEBUG and SECRET_KEY == _INSECURE_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "app.middleware.ImpersonationMiddleware",
    "app.middleware.RequiredProfileSetupMiddleware",
    "app.middleware.AuditActorMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cartei.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "app.context_processors.privileged",
            ],
        },
    }
]

WSGI_APPLICATION = "cartei.wsgi.application"

_db_url = urlparse(os.environ.get("DATABASE_URL", "postgresql://localhost/cartei"))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db_url.path.lstrip("/"),
        "USER": _db_url.username or "",
        "PASSWORD": _db_url.password or "",
        "HOST": _db_url.hostname or "localhost",
        "PORT": str(_db_url.port or 5432),
    }
}

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

# LDAP — skipped gracefully if python-ldap not installed
try:
    import ldap
    from django_auth_ldap.config import LDAPSearch, MemberDNGroupType

    AUTH_LDAP_SERVER_URI = os.environ.get("LDAP_SERVER_URI", "ldap://localhost")
    AUTH_LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", "")
    AUTH_LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")
    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        os.environ.get("LDAP_USER_SEARCH_BASE", "dc=example,dc=com"),
        ldap.SCOPE_SUBTREE,
        "(uid=%(user)s)",
    )
    AUTH_LDAP_USER_ATTR_MAP = {
        "first_name": "givenName",
        "last_name": "sn",
        "email": "mail",
    }
    AUTH_LDAP_GROUP_TYPE = MemberDNGroupType("member")
    AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
        os.environ.get("LDAP_GROUPS_BASE", "cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de"),
        ldap.SCOPE_SUBTREE,
        "(objectClass=groupOfNames)",
    )
    AUTH_LDAP_REQUIRE_GROUP = os.environ.get(
    "LDAP_REQUIRE_GROUP",
    "cn=confidentiality_clearance,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
    AUTH_LDAP_GLOBAL_OPTIONS = {ldap.OPT_REFERRALS: 0}
    _ca_cert = os.environ.get("LDAP_CA_CERT_PATH", "")
    if _ca_cert:
        try:
            ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, _ca_cert)
            AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_CACERTFILE] = _ca_cert
            AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_REQUIRE_CERT] = ldap.OPT_X_TLS_DEMAND
        except ValueError:
            # macOS Secure Transport does not support OPT_X_TLS_CACERTFILE
            AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_REQUIRE_CERT] = ldap.OPT_X_TLS_NEVER
            AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_NEWCTX] = 0

    AUTHENTICATION_BACKENDS = [
        "app.auth.CustomLDAPBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]
except ImportError:
    AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",
    ]

CARTEI_ADMIN_GROUP = os.environ.get(
    "CARTEI_ADMIN_GROUP",
    "cn=cartei_admin,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
CARTEI_CLUSTER_GROUP = os.environ.get(
    "CARTEI_CLUSTER_GROUP",
    "cn=gr.cluster,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
# Read+write tenant access. Like the admin/cluster groups it is not an AG-prefixed
# cn, so _sync_groups maps this DN to the "cartei_mietverwaltung" marker.
CARTEI_MIETVERWALTUNG_GROUP = os.environ.get(
    "CARTEI_MIETVERWALTUNG_GROUP",
    "cn=cartei_mietverwaltung,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
CARTEI_HELFER_MIETVERWALTUNG_GROUP = os.environ.get(
    "CARTEI_HELFER_MIETVERWALTUNG_GROUP",
    "cn=cartei_helfer_mietverwaltung,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
# LDAP group whose members may impersonate other users. _sync_groups maps this
# DN to the "cartei_impersonation" Django group (granted/revoked by membership
# on every login, like the other rights groups). A plain group — NOT is_superuser
# — so it grants only impersonation and nothing implicit. A missing or blank env
# value falls back to this standard DN.
CARTEI_IMPERSONATION_GROUP = os.environ.get("CARTEI_IMPERSONATION_GROUP") or (
    "cn=cartei_impersonation,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de"
)
LDAP_USER_SEARCH_BASE = os.environ.get(
    "LDAP_USER_SEARCH_BASE",
    "cn=users,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
LDAP_GROUPS_BASE = os.environ.get(
    "LDAP_GROUPS_BASE",
    "cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
LDAP_REQUIRE_GROUP = os.environ.get(
    "LDAP_REQUIRE_GROUP",
    "cn=confidentiality_clearance,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)

# FreeIPA provisioning (CArtei creates the account; see app/ldap_utils). Needs a
# service account holding the "CArtei Provisioner" role. Empty IPA_SERVER
# disables provisioning (dev / no-LDAP).
IPA_SERVER = os.environ.get("IPA_SERVER", "")
IPA_PROVISION_USER = os.environ.get("IPA_PROVISION_USER", "")
IPA_PROVISION_PASSWORD = os.environ.get("IPA_PROVISION_PASSWORD", "")
# "true"/"false", or a path to a CA bundle. FreeIPA serves HTTPS with its own CA
# (the same one that signs LDAPS), so if unset, trust the LDAP CA cert — else the
# API call fails with "self-signed certificate in certificate chain".
_ipa_verify = os.environ.get("IPA_VERIFY_SSL", "").strip()
if not _ipa_verify:
    IPA_VERIFY_SSL = os.environ.get("LDAP_CA_CERT_PATH", "") or True
elif _ipa_verify.lower() in ("true", "false"):
    IPA_VERIFY_SSL = _ipa_verify.lower() == "true"
else:
    IPA_VERIFY_SSL = _ipa_verify  # path to a CA bundle

# Email (SMTP) — tenant onboarding + automated notifications. Sends via the org
# mail relay (the same one Zammad uses); from a noreply address.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() != "false"
# Never let a dead/filtered relay hang a request — fail fast, then the caller
# links the account anyway and shows an "E-Mail fehlgeschlagen" warning.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@ca-hd.de")
# Onboarding email links. INTRANET_URL: where the tenant logs in. GUIDE: the
# how-to for changing the one-time password + setting up WLAN.
INTRANET_URL = os.environ.get("INTRANET_URL", "https://intranet.ca-hd.de/home")
PASSWORD_GUIDE_URL = os.environ.get("PASSWORD_GUIDE_URL", "https://collegiumacademicum.de/internet/")

# Maps a section role to the LDAP-synced Django group name(s) that grant it.
# These are the Django group names produced by app/auth.CustomLDAPBackend:
# the cluster LDAP group is synced as "gr.cluster"; AG groups keep their raw cn.
# Override per role via env with a comma-separated list, e.g.
#   TENANT_GROUP_MIETVERWALTUNG=ag.mietverwaltung,ag.hausverwaltung
def _group_list(env_key: str, default: str) -> list[str]:
    return [g.strip() for g in os.environ.get(env_key, default).split(",") if g.strip()]


TENANT_ROLE_GROUPS = {
    # "admins" is the synced marker name that CARTEI_ADMIN_GROUP maps to (see
    # app/auth.CustomLDAPBackend); the "admin" role can view/edit all fields.
    "admin": _group_list("TENANT_GROUP_ADMIN", "admins"),
    "cluster": _group_list("TENANT_GROUP_CLUSTER", "gr.cluster"),
    "belegium": _group_list("TENANT_GROUP_BELEGIUM", "gr.belegium"),
    "mietverwaltung": _group_list("TENANT_GROUP_MIETVERWALTUNG", "cartei_mietverwaltung"),
    "mietverwaltung_helfer": _group_list("TENANT_GROUP_MIETVERWALTUNG_HELFER", "cartei_helfer_mietverwaltung"),
    # AG Werkstatt: may edit room furniture (Ausstattung) only, nothing else.
    "werkstatt": _group_list("TENANT_GROUP_WERKSTATT", "cartei_werkstatt"),
    "finanzierung": _group_list("TENANT_GROUP_FINANZIERUNG", "cartei_finanzierung"),
}

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "false").lower() == "true"
_https = os.environ.get("HTTPS_ENABLED", "false").lower() == "true"
SESSION_COOKIE_SECURE = _https
CSRF_COOKIE_SECURE = _https
_csrf_origins = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING"},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
