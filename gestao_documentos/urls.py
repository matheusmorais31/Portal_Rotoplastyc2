from django.contrib import admin
from django.urls import path, include
from usuarios import views as usuarios_views
from gestao_documentos.views import home
from django.conf import settings
from django.conf.urls.static import static
from . import views  # Importa as views do projeto

# Define o manipulador de erro 403
handler403 = 'usuarios.views.error_403_view'

urlpatterns = [
    # Página inicial
    path('', home, name='home'),
    path('tecnicon/', views.tecnicon, name='tecnicon'),
    path('monitores/', views.monitores, name='monitores'),
    path('allcance/', views.allcance, name='allcance'),
    path('glpi/', views.glpi, name='glpi'),
    path('gestao/', views.gestao, name='gestao'),
    path('mural/', views.mural, name='mural'),
    path('manuais/', views.manuais, name='manuais'),
    path('andon/', views.andon, name='andon'),

    
    # Administração
    path('admin/', admin.site.urls),
    
    # Aplicativo de Usuários
    path('usuarios/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),
    path('perfil/', usuarios_views.ProfileView.as_view(), name='perfil_usuario'),
    
    # Aplicativo de Documentos
    path('documentos/', include('documentos.urls', namespace='documentos')),

    # Aplicativo de Notificações
    path('notificacoes/', include('notificacoes.urls')),

    #BI
    path('bi/', include('bi.urls', namespace='bi')),  # Inclui as URLs com o namespace 'bi'
]

# Configuração para servir arquivos de mídia e estáticos em modo de depuração
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
