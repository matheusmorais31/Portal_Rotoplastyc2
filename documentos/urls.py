# documentos/urls.py

from django.urls import path
from . import views

app_name = 'documentos'

urlpatterns = [
    path('categorias/', views.listar_categorias, name='listar_categorias'),
    path('categorias/criar/', views.criar_categoria, name='criar_categoria'),
    path('categorias/editar/<int:pk>/', views.editar_categoria, name='editar_categoria'),
    path('categorias/excluir/<int:pk>/', views.excluir_categoria, name='excluir_categoria'),

    # Rotas de documentos
    path('listar_documentos/', views.listar_documentos_aprovados, name='listar_documentos_aprovados'),
    path('aprovar_pendentes/', views.listar_aprovacoes_pendentes, name='listar_aprovacoes_pendentes'),
    path('documentos/criar/', views.criar_documento, name='criar_documento'),
    path('visualizar/<int:id>/', views.visualizar_documento, name='visualizar_documento'),
    path('aprovar/<int:documento_id>/', views.aprovar_documento, name='aprovar_documento'),
    path('reprovar/<int:documento_id>/', views.reprovar_documento, name='reprovar_documento'),
    path('documentos/nova_revisao/<int:documento_id>/', views.nova_revisao, name='nova_revisao'),
]