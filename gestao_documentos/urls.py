from django.contrib import admin
from django.urls import path, include
from usuarios import views
from django.contrib.auth.views import LogoutView
from django.conf import settings  # Importar settings
from django.conf.urls.static import static  # Importar static
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),  # Página inicial (home)
    path('usuarios/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),  # Inclui as URLs do app 'usuarios' com namespace
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('perfil/', views.ProfileView.as_view(), name='perfil_usuario'),  # Mude o nome para 'perfil_usuario' como no template
    # URLS DOCUMENTOS
    path('documentos/', include('documentos.urls', namespace='documentos')),
    # NOTIFICAÇÕES
    path('notificacoes/', include('notificacoes.urls')),
]

# Para servir arquivos de mídia durante o desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

