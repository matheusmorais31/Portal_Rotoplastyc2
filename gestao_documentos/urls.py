from django.contrib import admin
from django.urls import path, include
from usuarios import views as usuarios_views  # Importa as views do app 'usuarios'
from gestao_documentos import views as gestao_documentos_views  # Importa as views do app 'gestao_documentos'
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from gestao_documentos.views import home  # Importa a view home corrigida

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('usuarios/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),  # Inclui as URLs do app 'usuarios'
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('perfil/', usuarios_views.ProfileView.as_view(), name='perfil_usuario'),
    path('documentos/', include('documentos.urls', namespace='documentos')),  # URLs relacionadas a documentos
    path('notificacoes/', include('notificacoes.urls')),  # URLs relacionadas a notificações
     
    
]

# Para servir arquivos de mídia durante o desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
