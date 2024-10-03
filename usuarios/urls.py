from django.urls import path
from . import views

urlpatterns = [
    path('registrar/', views.registrar_usuario, name='registrar'),
    path('login/', views.login_usuario, name='login_usuario'),
    path('lista_usuarios/', views.lista_usuarios, name='lista_usuarios'),
    path('editar/<int:usuario_id>/', views.editar_usuario, name='editar_usuario'),
    path('buscar_usuarios/', views.buscar_usuarios_ad, name='buscar_usuarios_ad'),  # A rota está definida aqui
    path('importar_usuarios/', views.importar_usuarios_ad, name='importar_usuarios_ad'),
]
