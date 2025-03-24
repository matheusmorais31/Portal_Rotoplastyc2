from django.urls import path
from . import views

app_name = 'documentos'

urlpatterns = [
    # URLs para Gerenciamento de Categorias
    path('categorias/', views.listar_categorias, name='listar_categorias'),
    path('categorias/criar/', views.criar_categoria, name='criar_categoria'),
    path('categorias/editar/<int:pk>/', views.editar_categoria, name='editar_categoria'),
    path('categorias/excluir/<int:pk>/', views.excluir_categoria, name='excluir_categoria'),

    # URLs para Gerenciamento de Documentos
    path('criar/', views.criar_documento, name='criar_documento'),
    path('analise/', views.listar_documentos_para_analise, name='listar_documentos_para_analise'),
    path('aprovar/<int:documento_id>/', views.aprovar_documento, name='aprovar_documento'),
    path('substituir/<int:documento_id>/', views.substituir_documento, name='substituir_documento'),
    path('atualizar/<int:documento_id>/', views.atualizar_documento, name='atualizar_documento'),
    path('upload_revisado/<int:documento_id>/', views.upload_documento_revisado, name='upload_documento_revisado'),
    path('documento/<int:documento_id>/toggle-active/', views.toggle_documento_active_status, name='toggle_active_status'),
    path('documentos/inativos/', views.listar_documentos_inativos, name='listar_documentos_inativos'),



    # URLs para Aprovações Pendentes e Aprovados
    path('aprovacoes_pendentes/', views.listar_aprovacoes_pendentes, name='listar_aprovacoes_pendentes'),
    path('aprovados/', views.listar_documentos_aprovados, name='listar_documentos_aprovados'),
    path('reprovados/', views.listar_documentos_reprovados, name='listar_documentos_reprovados'),

    # URLs para Visualização de Documentos e PDFs
    path('visualizar/<int:id>/', views.visualizar_documento, name='visualizar_documento'),
    path('visualizar_pdf/<int:id>/', views.visualizar_pdf, name='visualizar_pdf'),
    path('visualizar_pdfjs/<int:id>/', views.visualizar_documento_pdfjs, name='visualizar_documento_pdfjs'),
 



    path('baixar_pdf/<int:id>/', views.baixar_pdf, name='baixar_pdf'),
    path('acessos/<int:id>/', views.visualizar_acessos_documento, name='visualizar_acessos_documento'),

    # URLs para Revisões e Documentos Editáveis
    path('nova_revisao/<int:documento_id>/', views.nova_revisao, name='nova_revisao'),
    path('editaveis/', views.listar_documentos_editaveis, name='listar_documentos_editaveis'),
    path('revisoes/<int:documento_id>/', views.listar_revisoes_documento, name='listar_revisoes_documento'),
    path('monitorar_pendentes/', views.monitorar_documentos_pendentes, name='monitorar_pendentes'),
    path('deletar/<int:documento_id>/', views.deletar_documento, name='deletar_documento'),



    


]
