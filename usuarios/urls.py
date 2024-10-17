<<<<<<< HEAD
# usuarios/urls.py

=======
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
from django.urls import path
from . import views

app_name = 'usuarios'

urlpatterns = [
    path('registrar/', views.registrar_usuario, name='registrar'),
    path('login/', views.login_usuario, name='login_usuario'),
    path('lista_usuarios/', views.lista_usuarios, name='lista_usuarios'),
    path('editar/<int:usuario_id>/', views.editar_usuario, name='editar_usuario'),
    path('buscar_usuarios/', views.buscar_usuarios_ad, name='buscar_usuarios_ad'),
    path('importar_usuarios/', views.importar_usuarios_ad, name='importar_usuarios_ad'),
    path('grupos/', views.lista_grupos, name='lista_grupos'),
    path('grupos/cadastrar_grupo/', views.cadastrar_grupo, name='cadastrar_grupo'),
    path('grupos/buscar_participantes/', views.buscar_participantes, name='buscar_participantes'),
    path('grupos/editar_grupo/<int:grupo_id>/', views.editar_grupo, name='editar_grupo'),
    path('grupos/excluir_grupo/<int:grupo_id>/', views.excluir_grupo, name='excluir_grupo'),
    path('liberar_permissoes/', views.liberar_permissoes, name='liberar_permissoes'),
<<<<<<< HEAD
    path('sugestoes/', views.sugestoes, name='sugestoes'),
=======
    path('sugestoes/', views.sugestoes, name='sugestoes'),  

>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
]
