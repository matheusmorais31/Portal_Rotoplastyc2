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
    
    path('listar_documentos/', views.listar_documentos, name='listar_documentos'),
    path('documentos/criar/', views.criar_documento, name='criar_documento'),
    # Adicione rotas para editar, excluir, visualizar documentos conforme necessário
]
