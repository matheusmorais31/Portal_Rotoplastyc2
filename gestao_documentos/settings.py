# settings.py
import os
import logging
import ssl
from pathlib import Path
from decouple import config # Mantenha apenas um import do config no topo
from django.urls import reverse_lazy
from dotenv import load_dotenv # IMPORTANTE: Adicionar esta linha

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# IMPORTANTE: Carrega variáveis do arquivo .env ANTES de qualquer chamada a config()
# Isso garante que o decouple encontre as variáveis definidas no seu .env
env_path = BASE_DIR / '.env' # Assume que o .env está na raiz do projeto (junto com manage.py)
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    # Opcional: logar um aviso se o .env não for encontrado.
    # O decouple então buscará apenas variáveis de ambiente reais do sistema.
    print(f"AVISO: Arquivo .env não encontrado em {env_path}. "
          f"Certifique-se de que as variáveis de ambiente estão definidas diretamente ou que o arquivo .env existe.")


# Quick-start development settings - unsuitable for production
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=True, cast=bool) # É uma boa prática pegar do .env e converter para bool
ALLOWED_HOSTS = [
    '172.16.44.12', 'localhost'    
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
    'ia',
    'rh',
    'formularios',
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
                'django.template.context_processors.csrf',
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
                # ATENÇÃO: ssl.CERT_NONE desabilita a verificação do certificado SSL.
                # Isso é INSEGURO para produção se você não confia na rede.
                # Considere usar um certificado CA apropriado.
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

# Internationalization
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
# USE_L10N = True # Deprecado a partir do Django 4.0, USE_I18N cobre a formatação localizada.
USE_TZ = False # Se False, datas/horas são ingênuas (naive). Se True, são cientes de fuso (aware) e TIME_ZONE é usado.


LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# LibreOffice configuration
_soffice_path_default = "/usr/bin/soffice"
if os.name == 'nt':  # Windows
    _soffice_path_default = r"C:\Program Files\LibreOffice\program\soffice.exe"
SOFFICE_PATH = config('SOFFICE_PATH', default=_soffice_path_default)


# Logging configuration with log rotation
LOGGING_DIR = BASE_DIR / 'logs'
LOGGING_DIR.mkdir(parents=True, exist_ok=True) # Garante que o diretório de logs exista

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} [{name}] {message}', # Adicionado [{name}] para ver a origem do logger
            'style': '{',
        },
    },
    'handlers': {
        'file_django': {
            'level': 'INFO', # Pode ser INFO para logs gerais do Django
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'django.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_documentos': { # Se você ainda usa este logger
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'documentos.log',
            'maxBytes': 1024 * 1024 * 5,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_email': { # Para o 'custom_email_logger'
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'email.log',
            'maxBytes': 1024 * 1024 * 5,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_bi': { # Se você ainda usa este logger
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'bi.log',
            'maxBytes': 1024 * 1024 * 5,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        # --- NOVO HANDLER PARA A APLICAÇÃO 'ia' ---
        'file_ia': {
            'level': 'DEBUG',  # Captura logs de nível DEBUG e acima para 'ia'
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'ia.log', # Nome do arquivo de log
            'maxBytes': 1024 * 1024 * 5,  # 5 MB por arquivo
            'backupCount': 5,             # Mantém 5 arquivos de backup
            'formatter': 'verbose',       # Usa o formatador detalhado
        },
        # --- FIM DO NOVO HANDLER ---
        'console': {
            'level': 'DEBUG', # Mostra logs DEBUG e acima no console durante o desenvolvimento
            'class': 'logging.StreamHandler',
            'formatter': 'simple', # Formato simples para o console
        },
        'file_formularios': {
            'level': 'DEBUG',                        # queremos capturar DEBUG
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'formularios.log',
            'maxBytes': 5 * 1024 * 1024,             # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file_django', 'console'],
            'level': 'INFO', # Nível para os logs do próprio Django
            'propagate': True,
        },
        'documentos': { # Se ainda relevante
            'handlers': ['file_documentos', 'console'],
            'level': 'DEBUG',
            'propagate': False, # False para não enviar para o logger 'django' ou root
        },
        'bi': { # Se ainda relevante
            'handlers': ['file_bi', 'console'],
            'level': 'DEBUG',
            'propagate': False, # Ajuste propagate conforme necessidade
        },
        'custom_email_logger': { # Para logs de e-mail
            'handlers': ['file_email', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        # --- NOVO LOGGER PARA A APLICAÇÃO 'ia' ---
        'ia': {  # Este nome ('ia') corresponderá a loggers como 'ia.views', 'ia.models', etc.
            'handlers': ['file_ia', 'console'], # Envia para 'ia.log' e para o console
            'level': 'DEBUG',          # Define o nível mínimo de log a ser capturado para esta app
            'propagate': False,        # Impede que as mensagens sejam passadas para loggers pai (root ou django)
                                       # Isso mantém o ia.log mais limpo e focado.
        },
        'formularios': {
            'handlers': ['file_formularios', 'console'],
            'level': 'DEBUG',          # habilita DEBUG
            'propagate': False,        # não envia para o logger “django”
        },
        
        # --- FIM DO NOVO LOGGER ---
    },
    # Opcional: Configuração do logger raiz para capturar logs não tratados por loggers específicos
    # 'root': {
    # 'handlers': ['console', 'file_django'], # Onde enviar logs "órfãos"
    # 'level': 'WARNING', # Nível para logs não especificados
    # }
}



# Authentication backends
AUTHENTICATION_BACKENDS = [
    'usuarios.auth_backends.ActiveDirectoryBackend',
    'django.contrib.auth.backends.ModelBackend', # Necessário para o admin e usuários locais
    # 'usuarios.authentication.CustomBackend', # Se este for diferente do ModelBackend, certifique-se que está correto
]


LIBREOFFICE_PATH = SOFFICE_PATH # Usa a variável já definida anteriormente


# Security settings
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Redirect URLs
LOGOUT_REDIRECT_URL = reverse_lazy('usuarios:login_usuario')
LOGIN_URL = reverse_lazy('usuarios:login_usuario')


# Tamanho máximo de upload em bytes (Exemplo: 500MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 524288000  # 500 * 1024 * 1024


# Configurações de e-mail (já definidas no topo via config, esta seção parece redundante se os nomes forem os mesmos)
# Se estas forem as configurações de e-mail, elas devem usar `config()` também.
# Por exemplo, se `EMAIL_HOST` já foi carregado via `config('EMAIL_HOST')` no topo, esta redefinição não é necessária.
# Vou assumir que as definições com `config()` são as principais.
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com') # Ou o valor do seu .env
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER') # Já carregado do .env se definido lá
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD') # Já carregado do .env se definido lá
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER) # Usa EMAIL_HOST_USER como padrão

SITE_URL = config('SITE_URL', default='http://127.0.0.1:8000')

# Celery Configuration Options
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE # Usa o TIME_ZONE já definido para o Django
DJANGO_CELERY_BEAT_TZ_AWARE = False


# ==============================================================================
# Power BI Configuration - AJUSTADO PARA MÉTODO ROPC
# ATENÇÃO: Esta abordagem ROPC é ALTAMENTE DESACONSELHADA para produção.
# Certifique-se de que estas variáveis estão definidas CORRETAMENTE no seu arquivo .env
# ==============================================================================
POWERBI_TENANT_ID = config('POWERBI_TENANT_ID', default=None)
POWERBI_USERNAME = config('POWERBI_USERNAME', default=None)
POWERBI_PASSWORD = config('POWERBI_PASSWORD', default=None)

# CRÍTICO: POWERBI_CLIENT_ID_FOR_ROPC deve ser um GUID (Client ID) de um App Registration
# no Azure AD configurado como "Cliente Público" com permissões delegadas para Power BI.
# O valor "gopNO9198saF8R0t0@!yTo?10!3856@6498" que você tinha no .env está INCORRETO.
POWERBI_CLIENT_ID_FOR_ROPC = config('POWERBI_CLIENT_ID_FOR_ROPC', default=None)

# ID do Workspace/Grupo padrão do Power BI. Útil independentemente do método de autenticação.
POWERBI_GROUP_ID_DEFAULT = config('POWERBI_GROUP_ID_DEFAULT', default=None)

POWERBI_CLIENT_ID = config("POWERBI_CLIENT_ID", default=None)
POWERBI_CLIENT_SECRET = config("POWERBI_CLIENT_SECRET", default="")
POWERBI_SCOPE = config(
    "POWERBI_SCOPE",
    default="https://analysis.windows.net/powerbi/api/.default"
)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
    }
}

# LDAP Configuration
LDAP_SERVER = config('LDAP_SERVER', default=None)
LDAP_USER = config('LDAP_USER', default=None) # DN de bind
LDAP_PASSWORD = config('LDAP_PASSWORD', default=None)
LDAP_SEARCH_BASE = config('LDAP_SEARCH_BASE', default=None)

CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Tempo de sessão
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=3600, cast=int) # 1 hora
SESSION_IDLE_TIMEOUT = config('SESSION_IDLE_TIMEOUT', default=3600, cast=int) # 1 hora, para o middleware customizado
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = config('SESSION_EXPIRE_AT_BROWSER_CLOSE', default=True, cast=bool)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

IA_MAX_FILE_EXTRACTION_CHARS = config('IA_MAX_FILE_EXTRACTION_CHARS', default=1000000, cast=int)  # 1 milhão de caracteres

# CHAVE IA
GEMINI_API_KEY = config('GEMINI_API_KEY', default=None)

# CHAVE API OpenAI
OPENAI_API_KEY = config('OPENAI_API_KEY', default=None)

ASSISTANT_ID = "asst_n3bjyIruC73ZJVgygOKRtaqU"



# Taxa de Câmbio (Exemplo)
from decimal import Decimal
USD_TO_BRL_RATE = config('USD_TO_BRL_RATE', default=Decimal("5.00"), cast=Decimal) # Adicionado cast e default