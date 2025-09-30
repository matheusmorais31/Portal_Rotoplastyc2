# settings.py
import os
import ssl
import base64
import hashlib
import logging
from pathlib import Path
from decouple import config
from django.urls import reverse_lazy
from dotenv import load_dotenv
from decimal import Decimal

# Base
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega .env cedo
env_path = BASE_DIR / '.env'
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    print(f"AVISO: Arquivo .env não encontrado em {env_path}. "
          f"Defina as variáveis de ambiente ou crie o .env.")

# Django core
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = ['172.16.44.12', 'localhost']

# Apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'django.contrib.humanize',

    # Terceiros
    'dirtyfields',
    'django_celery_beat',
    # 'django_htmx',  # opcional (necessário apenas se você usar template tags do pacote)

    # Apps do projeto
    'documentos.apps.DocumentosConfig',
    'usuarios.apps.UsuariosConfig',
    'notificacoes',
    'bi',
    'ia',
    'rh',
    'formularios',
    'sqlhub',
]

AUTH_USER_MODEL = 'usuarios.Usuario'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'usuarios.session_timeout_middleware.SessionIdleTimeoutMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'gestao_documentos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'gestao_documentos' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'notificacoes.context_processors.notificacoes_nao_lidas',
                'django.template.context_processors.csrf',
            ],
        },
    },
]

WSGI_APPLICATION = 'gestao_documentos.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {
            'ssl': {
                # AVISO: ssl.CERT_NONE desabilita verificação do certificado.
                # Evite em produção se não confiar na rede.
                'cert_reqs': ssl.CERT_NONE,
            }
        }
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# I18N/L10N
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = False

LOCALE_PATHS = [BASE_DIR / 'locale']

# Static & Media
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# LibreOffice
_soffice_path_default = "/usr/bin/soffice"
if os.name == 'nt':
    _soffice_path_default = r"C:\Program Files\LibreOffice\program\soffice.exe"
SOFFICE_PATH = config('SOFFICE_PATH', default=_soffice_path_default)
LIBREOFFICE_PATH = SOFFICE_PATH

# Logging
LOGGING_DIR = BASE_DIR / 'logs'
LOGGING_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}', 'style': '{'},
        'simple':  {'format': '{levelname} {asctime} [{name}] {message}', 'style': '{'},
    },
    'handlers': {
        'file_django': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'django.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_documentos': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'documentos.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_email': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'email.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_bi': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'bi.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_ia': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'ia.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_formularios': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'formularios.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },

        # Handler adicionado para sqlhub
        'file_sqlhub': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'sqlhub.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },

        'console': {'level': 'DEBUG', 'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'loggers': {
        'django':      {'handlers': ['file_django', 'console'], 'level': 'INFO', 'propagate': True},
        'documentos':  {'handlers': ['file_documentos', 'console'], 'level': 'DEBUG', 'propagate': False},
        'bi':          {'handlers': ['file_bi', 'console'], 'level': 'DEBUG', 'propagate': False},
        'custom_email_logger': {'handlers': ['file_email', 'console'], 'level': 'INFO', 'propagate': False},
        'ia':          {'handlers': ['file_ia', 'console'], 'level': 'DEBUG', 'propagate': False},
        'formularios': {'handlers': ['file_formularios', 'console'], 'level': 'DEBUG', 'propagate': False},

        # Logger adicionado para sqlhub
        'sqlhub': {'handlers': ['file_sqlhub', 'console'], 'level': 'DEBUG', 'propagate': False},
    },
}

# Auth backends
AUTHENTICATION_BACKENDS = [
    'usuarios.auth_backends.ActiveDirectoryBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Segurança/Headers
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Redirects
LOGOUT_REDIRECT_URL = reverse_lazy('usuarios:login_usuario')
LOGIN_URL = reverse_lazy('usuarios:login_usuario')

# Upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 500 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 500 * 1024 * 1024

# Email (via .env)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

SITE_URL = config('SITE_URL', default='http://127.0.0.1:8000')

# Celery
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
DJANGO_CELERY_BEAT_TZ_AWARE = False
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Caches
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
    }
}

# LDAP
LDAP_SERVER = config('LDAP_SERVER', default=None)
LDAP_USER = config('LDAP_USER', default=None)
LDAP_PASSWORD = config('LDAP_PASSWORD', default=None)
LDAP_SEARCH_BASE = config('LDAP_SEARCH_BASE', default=None)

# Sessão
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=3600, cast=int)
SESSION_IDLE_TIMEOUT = config('SESSION_IDLE_TIMEOUT', default=3600, cast=int)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = config('SESSION_EXPIRE_AT_BROWSER_CLOSE', default=True, cast=bool)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# IA / APIs
IA_MAX_FILE_EXTRACTION_CHARS = config('IA_MAX_FILE_EXTRACTION_CHARS', default=1000000, cast=int)
GEMINI_API_KEY = config('GEMINI_API_KEY', default=None)
OPENAI_API_KEY = config('OPENAI_API_KEY', default=None)
ASSISTANT_ID = "asst_n3bjyIruC73ZJVgygOKRtaqU"

# Power BI (ROPC - use com cautela)
POWERBI_TENANT_ID = config('POWERBI_TENANT_ID', default=None)
POWERBI_USERNAME = config('POWERBI_USERNAME', default=None)
POWERBI_PASSWORD = config('POWERBI_PASSWORD', default=None)
POWERBI_CLIENT_ID_FOR_ROPC = config('POWERBI_CLIENT_ID_FOR_ROPC', default=None)
POWERBI_GROUP_ID_DEFAULT = config('POWERBI_GROUP_ID_DEFAULT', default=None)
POWERBI_CLIENT_ID = config("POWERBI_CLIENT_ID", default=None)
POWERBI_CLIENT_SECRET = config("POWERBI_CLIENT_SECRET", default="")
POWERBI_SCOPE = config("POWERBI_SCOPE", default="https://analysis.windows.net/powerbi/api/.default")

# Taxa de câmbio (exemplo)
USD_TO_BRL_RATE = config('USD_TO_BRL_RATE', default=Decimal("5.00"), cast=Decimal)

# ====== CHAVES FERNET (para criptografia do sqlhub/fields.py) ======
FERNET_KEYS = [os.getenv("FERNET_KEY")]

# Fallback seguro: se não houver FERNET_KEY, deriva a partir da SECRET_KEY
if not FERNET_KEYS or not FERNET_KEYS[0]:
    digest = hashlib.sha256(SECRET_KEY.encode()).digest()
    FERNET_KEYS = [base64.urlsafe_b64encode(digest).decode()]

# ====== CLIMATEMPO  ======  # <<<
CLIMATEMPO_TOKEN = config('CLIMATEMPO_TOKEN', default=None)         # <<<
CLIMATEMPO_CIDADE_ID = config('CLIMATEMPO_CIDADE_ID', default=5585, cast=int)  # <<<


# ====== OPEN-METEO  ======
OPENMETEO_LAT = config('OPENMETEO_LAT', default=-28.28389, cast=float)   # Carazinho-RS
OPENMETEO_LON = config('OPENMETEO_LON', default=-52.78639, cast=float)
OPENMETEO_TIMEZONE = config('OPENMETEO_TIMEZONE', default=TIME_ZONE)

