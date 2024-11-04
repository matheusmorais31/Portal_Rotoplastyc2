from django.contrib import admin
from django.urls import path, include
from usuarios import views as usuarios_views  # Importa as views do app 'usuarios'
from gestao_documentos.views import home  # Importa a view home
from django.conf.urls import handler403  # Importa o handler403
from django.conf import settings
from django.conf.urls.static import static

handler403 = 'usuarios.views.error_403_view'  # Define o manipulador de erro 403

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('usuarios/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),
    path('perfil/', usuarios_views.ProfileView.as_view(), name='perfil_usuario'),
    path('documentos/', include('documentos.urls', namespace='documentos')),
    path('notificacoes/', include('notificacoes.urls')),
    # Remova duplicações de 'usuarios' se houver
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
