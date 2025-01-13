"""
Base settings to build other settings files upon.
"""

# Django
from celery.schedules import crontab

# Standard Library
from datetime import timedelta

# Third Party
import environ

ROOT_DIR = (
    environ.Path(__file__) - 3
)  # (squarelet/config/settings/base.py - 3 = squarelet/)
APPS_DIR = ROOT_DIR.path("squarelet")
FRONTEND = ROOT_DIR.path("frontend")

env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(ROOT_DIR.path(".env")))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "America/New_York"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
ENV = env("DJANGO_ENV", default="dev")

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.admin",
    "django.forms",
]
THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "crispy_forms",
    "dal",
    "dal_select2",
    "debug_toolbar",
    "django_extensions",
    "django_premailer",
    "hijack",
    "oidc_provider",
    "rest_framework",
    "rest_framework.authtoken",
    "reversion",
    "rules.apps.AutodiscoverRulesConfig",
    "sorl.thumbnail",
    "corsheaders",
    "django_filters",
    "django_vite",
    "robots",
]
LOCAL_APPS = [
    "squarelet.core",
    "squarelet.oidc",
    "squarelet.organizations.apps.OrganizationsConfig",
    "squarelet.statistics",
    "squarelet.users.apps.UsersConfig",
    "allauth.socialaccount.providers.github",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "rules.permissions.ObjectPermissionBackend",
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
    "sesame.backends.ModelBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ["username", "name", "email"]},
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "dogslow.WatchdogMiddleware",
    "squarelet.core.middleware.PressPassCookieMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "sesame.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "oidc_provider.middleware.SessionManagementMiddleware",
    "squarelet.oidc.middleware.CacheInvalidationSenderMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "reversion.middleware.RevisionMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# FOR PRESSPASS FRONTEND
# ------------------------------------------------------------------------------

# The CSRF_TRUSTED_ORIGINS environment variable should be set to include the host names
# of the frontend, separated by spaces. A reasonable env setting for a development environment is:
# CSRF_TRUSTED_ORIGINS=http://dev.presspass.com:3000 http://localhost:3000 http://localhost:4200 http://127.0.0.1:3000 http://127.0.0.1:4200

# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-trusted-origins
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(ROOT_DIR("staticfiles"))
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [
    str(FRONTEND),
    str(FRONTEND.path("dist")),
]

# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

DJANGO_VITE = {
    "default": {
        "dev_mode": DEBUG,
        "manifest_path": str(ROOT_DIR.path("frontend/dist/manifest.json")),
    }
}

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR("media"))
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#template-dirs
        "DIRS": [str(APPS_DIR.path("templates"))],
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-debug
            "debug": DEBUG,
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-loaders
            # https://docs.djangoproject.com/en/dev/ref/templates/api/#loader-types
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "squarelet.core.context_processors.settings",
                "squarelet.core.context_processors.payment_failed",
                "squarelet.core.context_processors.payment_failed",
            ],
        },
    }
]
# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap4"

CRISPY_CLASS_CONVERTERS = {"textinput": "", "form-group": "_cls-field"}

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR.path("fixtures")),)

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
# https://docs.djangoproject.com/en/dev/ref/settings/#default-from-email
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL", default="MuckRock <info@muckrock.com>"
)
PRESSPASS_FROM_EMAIL = env(
    "PRESSPASS_FROM_EMAIL", default="PressPass <info@presspass.it>"
)
# https://docs.djangoproject.com/en/dev/ref/settings/#server-email
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env("DJANGO_EMAIL_SUBJECT_PREFIX", default="[MuckRock Accounts]")

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [("""Mitchell Kotler""", "mitch@muckrock.com")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s "
            "%(process)d %(thread)d %(message)s"
        }
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}
if DEBUG:
    LOGGING["loggers"] = {
        "rules": {"handlers": ["console"], "level": "DEBUG", "propagate": True}
    }

# Celery
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["squarelet.taskapp.celery.CeleryAppConfig"]
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = env("REDIS_URL", default="django://")
BROKER_URL = CELERY_BROKER_URL
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-result_backend
if CELERY_BROKER_URL == "django://":
    CELERY_RESULT_BACKEND = "redis://"
else:
    CELERY_RESULT_BACKEND = CELERY_BROKER_URL
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
CELERY_REDIS_MAX_CONNECTIONS = env.int("CELERY_REDIS_MAX_CONNECTIONS", default=10)


CELERY_BEAT_SCHEDULE = {
    "db_cleanup": {
        "task": "squarelet.core.tasks.db_cleanup",
        "schedule": crontab(day_of_week="sun", hour=1, minute=0),
    },
    "restore_organization": {
        "task": "squarelet.organizations.tasks.restore_organization",
        "schedule": crontab(hour=0, minute=5),
    },
    "store_statistics": {
        "task": "squarelet.statistics.tasks.store_statistics",
        "schedule": crontab(hour=5, minute=30),
    },
    "send_digest": {
        "task": "squarelet.statistics.tasks.send_digest",
        "schedule": crontab(hour=7, minute=0),
    },
}

# django-allauth
# ------------------------------------------------------------------------------
# https://django-allauth.readthedocs.io/en/latest/configuration.html
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
ACCOUNT_AUTHENTICATION_METHOD = "username_email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_ADAPTER = "squarelet.users.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "squarelet.users.adapters.SocialAccountAdapter"
SOCIALACCOUNT_STORE_TOKENS = True
ACCOUNT_FORMS = {
    "signup": "squarelet.users.forms.SignupForm",
    "login": "squarelet.users.forms.LoginForm",
    "add_email": "squarelet.users.forms.AddEmailForm",
    "change_password": "squarelet.users.forms.ChangePasswordForm",
    "set_password": "squarelet.users.forms.SetPasswordForm",
    "reset_password": "squarelet.users.forms.ResetPasswordForm",
    "reset_password_from_key": "squarelet.users.forms.ResetPasswordKeyForm",
}
ACCOUNT_SIGNUP_PASSWORD_ENTER_TWICE = False
ACCOUNT_SESSION_REMEMBER = True

DIGEST_EMAILS = env.list("DIGEST_EMAILS", default=[])

# django-compressor
# ------------------------------------------------------------------------------
# https://django-compressor.readthedocs.io/en/latest/quickstart/#installation
INSTALLED_APPS += ["compressor"]
STATICFILES_FINDERS += ["compressor.finders.CompressorFinder"]
# Your stuff...
# ------------------------------------------------------------------------------

# oidc
# ------------------------------------------------------------------------------
OIDC_USERINFO = "squarelet.users.oidc.userinfo"
OIDC_EXTRA_SCOPE_CLAIMS = "squarelet.users.oidc.CustomScopeClaims"
OIDC_SESSION_MANAGEMENT_ENABLE = True
OIDC_GRANT_TYPE_PASSWORD_ENABLE = True
OIDC_AFTER_USERLOGIN_HOOK = "squarelet.oidc.utils.oidc_login_hook"
# Allows session cookie to be used in OAuth
SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = True
ENABLE_SEND_CACHE_INVALIDATIONS = env.bool(
    "ENABLE_SEND_CACHE_INVALIDATIONS", default=True
)


# rest framework
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "squarelet.oidc.authentication.OidcOauth2Authentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "PAGE_SIZE": 100,
}

# first party urls
# ------------------------------------------------------------------------------
SQUARELET_URL = env("SQUARELET_URL", default="https://dev.squarelet.com")
MUCKROCK_URL = env("MUCKROCK_URL", default="https://dev.muckrock.com")
FOIAMACHINE_URL = env("FOIAMACHINE_URL", default="https://dev.foiamachine.org")
DOCCLOUD_URL = env("DOCCLOUD_URL", default="https://www.dev.documentcloud.org")
BIGLOCALNEWS_URL = env("BIGLOCALNEWS_URL", default="https://local.biglocalnews.org")
BIGLOCALNEWS_API_URL = env(
    "BIGLOCALNEWS_API_URL", default="https://local-api.biglocalnews.org"
)
AGENDAWATCH_URL = env("AGENDAWATCH_URL", default="https://agendawatch.org")
PRESSPASS_URL = env("PRESSPASS_URL", default="https://dev.presspass.com:3000")
PRESSPASS_API_URL = env("PRESSPASS_API_URL", default="https://dev.presspass.com")

PRESSPASS_DOMAIN = env("PRESSPASS_DOMAIN", default="")
PRESSPASS_COOKIE_DOMAIN = env("PRESSPASS_COOKIE_DOMAIN", default="")

# stripe
# ------------------------------------------------------------------------------
STRIPE_PUB_KEY = env("STRIPE_PUB_KEY")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET")

# mailgun
# ------------------------------------------------------------------------------
MAILGUN_ACCESS_KEY = env("MAILGUN_ACCESS_KEY")


# sesame
# ------------------------------------------------------------------------------
SESAME_MAX_AGE = 60 * 60 * 24 * 2  # 2 days
SESAME_ONE_TIME = True


# django-debug-toolbar
# ------------------------------------------------------------------------------
def show_toolbar(request):
    """show toolbar on the site"""
    return env.bool("SHOW_DDT", default=False) or (
        request.user and request.user.username == "mitch"
    )


DEBUG_TOOLBAR_CONFIG = {
    "INTERCEPT_REDIRECT": False,
    "SHOW_TEMPLATE_CONTEXT": True,
    "SHOW_TOOLBAR_CALLBACK": show_toolbar,
}
# django-hijack
# ------------------------------------------------------------------------------
HIJACK_AUTHORIZE_STAFF = True

# dogslow
# ------------------------------------------------------------------------------
DOGSLOW = True
DOGSLOW_LOG_TO_FILE = False
DOGSLOW_TIMER = 25
DOGSLOW_EMAIL_TO = "mitch@muckrock.com"
DOGSLOW_EMAIL_FROM = "info@muckrock.com"
DOGSLOW_LOGGER = "dogslow"  # can be anything, but must match `logger` below
DOGSLOW_LOG_TO_SENTRY = True

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# simplejwt
# ------------------------------------------------------------------------------

SIMPLE_JWT = {
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "RS256",
    "AUDIENCE": ["squarelet", "muckrock", "documentcloud"],
    "ISSUER": ["squarelet"],
    "USER_ID_FIELD": "uuid",
    # These are set in `users/apps.py` as they need to fetch from the database
    "SIGNING_KEY": "",
    "VERIFYING_KEY": "",
    # These are used for testing token expiration
    # "ACCESS_TOKEN_LIFETIME": timedelta(seconds=2),
    # "REFRESH_TOKEN_LIFETIME": timedelta(seconds=5),
}

# django-cors-headers
# ------------------------------------------------------------------------------

# The CORS_ORIGIN_WHITELIST environment variable should be set to include the host names
# of the frontend, separated by spaces. A reasonable env setting for a development environment is:
# CORS_ORIGIN_WHITELIST=http://dev.presspass.com:3000 http://localhost:3000 http://localhost:4200 http://127.0.0.1:3000 http://127.0.0.1:4200

CORS_ORIGIN_WHITELIST = env.list("CORS_ORIGIN_WHITELIST", default=[])
CORS_ALLOW_CREDENTIALS = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

USE_PLAUSIBLE = env.bool("USE_PLAUSIBLE", default=True)

MAILCHIMP_API_KEY = env("MAILCHIMP_API_KEY", default="")
MAILCHIMP_API_ROOT = "https://us2.api.mailchimp.com/3.0"
MAILCHIMP_LIST_DEFAULT = "a34d93cbe8"

# Election Hub
# ------------------------------------------------------------------------------
ERH_CATALOG_ENABLED = env.bool("ERH_CATALOG_ENABLED", default=False)
ERH_NAV_ENABLED = env.bool("ERH_NAV_ENABLED", default=False)
AIRTABLE_ACCESS_TOKEN = env("AIRTABLE_ACCESS_TOKEN", default="")
AIRTABLE_ERH_BASE_ID = env("AIRTABLE_ERH_BASE_ID", default="")
AIRTABLE_CACHE_TTL = env.int("AIRTABLE_CACHE_TTL", default=30)

# Robots.txt
# ------------------------------------------------------------------------------
ROBOTS_CACHE_TIMEOUT = 60 * 60 * 24
