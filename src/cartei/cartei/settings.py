# settings.py
import logging
import os
from pathlib import Path

import ldap
from django_auth_ldap.config import GroupOfNamesType, LDAPSearch
from dotenv import load_dotenv

load_dotenv()

LOCAL_DEV = os.getenv("LOCAL_DEV", "false") == "true"
if LOCAL_DEV:
    print("Running in LOCAL_DEV mode")

# The URL of your LDAP server
AUTH_LDAP_SERVER_URI = "ldaps://ipa.intranet.ca-hd.de"

# The DN and password to bind with (if needed)
AUTH_LDAP_BIND_DN = "uid=service_cartei,cn=users,cn=accounts,dc=intranet,dc=ca-hd,dc=de"
AUTH_LDAP_BIND_PASSWORD = "LvPqxZhGBuNYNqJJSLfnqf5BeESq72LxZSPxTFBj3E"


# The base DN for searching for users
AUTH_LDAP_USER_SEARCH = LDAPSearch("cn=users,cn=accounts,dc=intranet,dc=ca-hd,dc=de", ldap.SCOPE_SUBTREE, "(uid=%(user)s)")


AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    "cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
    ldap.SCOPE_SUBTREE,
    "(objectClass=ipausergroup)",
)
AUTH_LDAP_GROUP_TYPE = GroupOfNamesType()


# Simple group restrictions
AUTH_LDAP_REQUIRE_GROUP = "cn=ag.it,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de"
# AUTH_LDAP_DENY_GROUP = None

# Cache group memberships for an hour to minimize LDAP traffic
AUTH_LDAP_CACHE_GROUPS = True
AUTH_LDAP_GROUP_CACHE_TIMEOUT = 3600

# Enable LDAP authentication backend
if LOCAL_DEV:
    AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",  # Default authentication for dev
    ]
else:
    AUTHENTICATION_BACKENDS = [
        "django_auth_ldap.backend.LDAPBackend",  # LDAP for production
        "django.contrib.auth.backends.ModelBackend",
    ]


# Logging configuration to help with debugging
logger = logging.getLogger("django_auth_ldap")
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-sr0k2f-@gu14j&0w0%td1jgm%u0uq=n-kihe5+ea!v@fqfy4k("

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    "app",
    "crispy_bootstrap5",
    "crispy_forms",
    "django_icons",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "widget_tweaks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cartei.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "cartei.wsgi.application"


# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases

DATABASES = {
    "default": (
        {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
        if LOCAL_DEV
        else {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DATABASE_NAME", "postgres"),
            "USER": os.getenv("DATABASE_USER", "postgres"),
            "PASSWORD": os.getenv("DATABASE_PASSWORD"),
            "HOST": os.getenv("DATABASE_HOST", "10.10.33.14"),
            "PORT": os.getenv("DATABASE_PORT", "5432"),
        }
    )
}


# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = "/static/"

LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"  # Redirect to the home page after logout

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
