# Generated by Django 5.1.2 on 2024-12-09 16:53

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0026_documento_document_type'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='acesso',
            options={'default_permissions': (), 'permissions': [('view_acesso', 'Visualizar Acessos'), ('add_acesso', 'Adicionar Acesso'), ('change_acesso', 'Editar Acesso'), ('delete_acesso', 'Deletar Acesso')]},
        ),
        migrations.AlterModelOptions(
            name='categoria',
            options={'default_permissions': (), 'permissions': [('view_categoria', 'Visualizar Categorias'), ('add_categoria', 'Adicionar Categoria'), ('change_categoria', 'Editar Categoria'), ('delete_categoria', 'Deletar Categoria')]},
        ),
        migrations.AlterModelOptions(
            name='documento',
            options={'default_permissions': (), 'permissions': [('view_documentos', 'Listar Documentos'), ('can_add_documento', 'Adicionar Documento'), ('can_change_documento', 'Editar Documento'), ('can_delete_documento', 'Deletar Documento'), ('can_active', 'Pode ativar/inativar documentos'), ('view_acessos_documento', 'Visualizar Acessos Documentos'), ('can_view_revisions', 'Visualizar revisões de Documentos'), ('view_documentos_ina', 'Listar Documentos Inativos'), ('list_pending_approvals', 'Aprovações Pendentes'), ('list_reproaches', 'Lista Reprovações'), ('can_approve', 'Pode aprovar documentos'), ('can_analyze', 'Pode analisar documentos'), ('can_view_editables', 'Lista Editáveis')]},
        ),
    ]