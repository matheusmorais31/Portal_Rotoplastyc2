import os
import logging
import ssl
from pathlib import Path
from decouple import config
from django.urls import reverse_lazy



# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
SECRET_KEY = config('SECRET_KEY')
DEBUG = True
ALLOWED_HOSTS = [
    '172.16.44.12',       
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'documentos.apps.DocumentosConfig',
    'usuarios.apps.UsuariosConfig',
    'django.contrib.humanize',
    'notificacoes',
    'dirtyfields',
    'django_celery_beat',
    'bi',
    
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
            ],
        },
    },
]

WSGI_APPLICATION = 'gestao_documentos.wsgi.application'

# Database configuration
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
                'cert_reqs': ssl.CERT_NONE,
            }
        }
    }
}

# Password validation
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

# Internationalization
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_L10N = True
USE_TZ = False


LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]  # Certifique-se de que esta pasta existe
STATIC_ROOT = BASE_DIR / 'staticfiles'   # Diretório para coletar arquivos estáticos

# Media files (uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'          # Diretório para arquivos de mídia

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# LibreOffice configuration
# Adiciona o caminho do executável do LibreOffice, ajustável por sistema operacional
if os.name == 'nt':  # Windows
    SOFFICE_PATH = r"C:\Program Files\LibreOffice\program\soffice.exe"
else:  # Linux/Unix (incluindo Debian)
    SOFFICE_PATH = "/usr/bin/soffice"

# Alternativamente, utilize variáveis de ambiente para flexibilidade
SOFFICE_PATH = os.getenv('SOFFICE_PATH', SOFFICE_PATH)

# Logging configuration with log rotation
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,  # Preserva os loggers já existentes
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file_django': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_documentos': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'documentos.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_email': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'email.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_bi': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'bi.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file_django'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'documentos': {
            'handlers': ['file_documentos'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'email': {
            'handlers': ['file_email'],
            'level': 'INFO',
            'propagate': False,
        },
        'bi': {
            'handlers': ['file_bi'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}


# Authentication backends
AUTHENTICATION_BACKENDS = [
    'usuarios.auth_backends.ActiveDirectoryBackend',
    'django.contrib.auth.backends.ModelBackend',
    'usuarios.authentication.CustomBackend',
]


LIBREOFFICE_PATH = '/usr/bin/soffice'


# Security settings
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Redirect URLs
LOGOUT_REDIRECT_URL = reverse_lazy('usuarios:login_usuario')
LOGIN_URL = reverse_lazy('usuarios:login_usuario')



# Tamanho máximo de upload em bytes (Exemplo: 500MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 * 1024 * 1024



# settings.py

from decouple import config

# Configurações de e-mail
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# URL do site (utilizado para construir links completos)
SITE_URL = config('SITE_URL', default='http://172.16.44.12:8000')

# Celery Configuration Options
CELERY_BROKER_URL = 'redis://localhost:6379/0'  # Exemplo usando Redis
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'America/Sao_Paulo'  # Ajuste conforme sua região




# Power BI Configuration
POWERBI_CLIENT_ID = config('POWERBI_CLIENT_ID') 
POWERBI_CLIENT_SECRET = config('POWERBI_CLIENT_SECRET')
POWERBI_TENANT_ID = config('POWERBI_TENANT_ID')
POWERBI_GROUP_ID = config('POWERBI_GROUP_ID')

# settings.py



LDAP_SERVER = config('LDAP_SERVER')
LDAP_USER = config('LDAP_USER')
LDAP_PASSWORD = config('LDAP_PASSWORD')
LDAP_SEARCH_BASE = config('LDAP_SEARCH_BASE')

CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

#Tempo de sessão
SESSION_COOKIE_AGE = 3600
SESSION_IDLE_TIMEOUT = 3600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
#Gravar sessão
SESSION_ENGINE = 'django.contrib.sessions.backends.db'