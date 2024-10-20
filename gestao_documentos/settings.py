import os, logging
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
SECRET_KEY = 'django-insecure-1hy@(6*s2-g(gw)gh800lp_&&+0pm5-*kyl0zqetl%*^5-=8ig'
DEBUG = True
ALLOWED_HOSTS = []

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
    'django.middleware.csrf.CsrfViewMiddleware', 
]

ROOT_URLCONF = 'gestao_documentos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'gestao_documentos', 'templates')],
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

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'portal_rotoplastyc',
        'USER': 'root',
        'PASSWORD': 'Admin@123',
        'HOST': '192.168.0.12',  # ou o endereço do servidor MySQL
        'PORT': '3306',
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
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files (uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Logging configuration with log rotation
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,  # Desativar loggers existentes
    'handlers': {
        'console': {
            'level': 'WARNING',  # Muda o nível de log para WARNING (vai ignorar INFO e DEBUG)
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',  # Ajuste o nível para WARNING, ERROR ou CRITICAL
            'propagate': True,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'ERROR',  # Apenas erros de banco de dados serão mostrados
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',  # Apenas erros de requisição serão exibidos
            'propagate': False,
        },
        'myapp': {  # Substitua 'myapp' pelo nome do seu app
            'handlers': ['console'],
            'level': 'ERROR',  # Apenas erros da sua aplicação serão exibidos
        },
    },
}
# Authentication backends
AUTHENTICATION_BACKENDS = [
    'usuarios.auth_backends.ActiveDirectoryBackend',  # Certifique-se de que o caminho está correto
    'django.contrib.auth.backends.ModelBackend',
]

# Security settings
X_FRAME_OPTIONS = 'SAMEORIGIN'
