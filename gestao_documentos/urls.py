from django.contrib import admin
from django.urls import path, include
from usuarios import views as usuarios_views
from gestao_documentos.views import home
from django.conf import settings
from django.conf.urls.static import static

# Define o manipulador de erro 403
handler403 = 'usuarios.views.error_403_view'

urlpatterns = [
    # Página inicial
    path('', home, name='home'),
    
    # Administração
    path('admin/', admin.site.urls),
    
    # Aplicativo de Usuários
    path('usuarios/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),
    path('perfil/', usuarios_views.ProfileView.as_view(), name='perfil_usuario'),
    
    # Aplicativo de Documentos
    path('documentos/', include('documentos.urls', namespace='documentos')),

    # Aplicativo de Notificações
    path('notificacoes/', include('notificacoes.urls')),
]

# Configuração para servir arquivos de mídia e estáticos em modo de depuração
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
