# Generated by Django 5.1.2 on 2024-11-22 21:55

import django.core.files.storage
import documentos.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0024_alter_documento_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='documento',
            options={'default_permissions': (), 'permissions': [('view_documentos', 'Listar Documentos'), ('can_add_documento', 'Adicionar Documento'), ('can_active', 'Pode ativar/inativar documentos'), ('view_acessos_documento', 'Visualizar Acessos Documentos'), ('can_view_revisions', 'Visualizar revisões de Documentos'), ('view_documentos_ina', 'Listar Documentos Inativos'), ('list_pending_approvals', 'Aprovações Pendentes'), ('list_reproaches', 'Lista Reprovações'), ('can_approve', 'Pode aprovar documentos'), ('can_analyze', 'Pode analisar documentos'), ('can_view_editables', 'Lista Editáveis'), ('view_categoria', 'Lista Categorias'), ('add_categoria', 'Adicionar Categoria'), ('change_categoria', 'Editar Categoria'), ('delete_categoria', 'Deletar Categoria')]},
        ),
        migrations.AddField(
            model_name='documento',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Indica se o documento está ativo.'),
        ),
        migrations.AlterField(
            model_name='documento',
            name='documento_pdf',
            field=models.FileField(blank=True, editable=False, null=True, storage=django.core.files.storage.FileSystemStorage(base_url=None, location='/opt/Portal_Rotoplastyc/media'), upload_to=documentos.models.pdf_upload_path),
        ),
    ]