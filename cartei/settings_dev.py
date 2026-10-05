"""Isolated local development settings for the Compose stack."""

import os

from .settings import *  # noqa: F403

DEBUG = True
SECRET_KEY = "cartei-local-development-only"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web"]
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
IPA_SERVER = ""
IPA_PROVISION_USER = ""
IPA_PROVISION_PASSWORD = ""
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
DEV_SEED_ENABLED = True
DEV_SUPERUSER_PASSWORD = os.environ.get("DEV_SUPERUSER_PASSWORD", "cartei-dev")
