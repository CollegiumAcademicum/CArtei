# settings.py
from dotenv import load_dotenv
import os
import ldap
from django_auth_ldap.config import LDAPSearch, GroupOfNamesType
load_dotenv()
# The URL of your LDAP server
AUTH_LDAP_SERVER_URI = "ldaps://ipa.intranet.ca-hd.de"

# The DN and password to bind with (if needed)
AUTH_LDAP_BIND_DN = 'uid=service_cartei,cn=users,cn=accounts,dc=intranet,dc=ca-hd,dc=de'
AUTH_LDAP_BIND_PASSWORD = "LvPqxZhGBuNYNqJJSLfnqf5BeESq72LxZSPxTFBj3E"


# The base DN for searching for users
AUTH_LDAP_USER_SEARCH = LDAPSearch("cn=users,cn=accounts,dc=intranet,dc=ca-hd,dc=de", ldap.SCOPE_SUBTREE, "(uid=%(user)s)")


AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
        'cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de',
        ldap.SCOPE_SUBTREE,
        '(objectClass=ipausergroup)',
    )
AUTH_LDAP_GROUP_TYPE = GroupOfNamesType()


# Simple group restrictions
AUTH_LDAP_REQUIRE_GROUP = "cn=ag.it,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de"
#AUTH_LDAP_DENY_GROUP = None

# Cache group memberships for an hour to minimize LDAP traffic
AUTH_LDAP_CACHE_GROUPS = True
AUTH_LDAP_GROUP_CACHE_TIMEOUT = 3600

# Enable LDAP authentication backend
AUTHENTICATION_BACKENDS = (
    'django_auth_ldap.backend.LDAPBackend',
    'django.contrib.auth.backends.ModelBackend',
)


# Logging configuration to help with debugging
import logging
logger = logging.getLogger('django_auth_ldap')
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = 'asdnkladfgöjniagnioa'

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'widget_tweaks',
    'freeipa_auth',
    # Add your other apps here
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'freeipa_auth.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'freeipa_auth.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DATABASE_NAME', 'postgres'),
        'USER': os.getenv('DATABASE_USER', 'postgres'),
        'PASSWORD': os.getenv('DATABASE_PASSWORD'),
        'HOST': os.getenv('DATABASE_HOST', '10.10.33.14'),
        'PORT': os.getenv('DATABASE_PORT', '5432'),
    }
#    'default': {
#        'ENGINE': 'django.db.backends.sqlite3',
#        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
#    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

STATIC_URL = '/static/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'  # Redirect to the home page after logout
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'