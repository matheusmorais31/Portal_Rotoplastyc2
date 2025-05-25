# documentos/migrations/0045_populate_codigo_revisoes.py
from django.db import migrations
import uuid


def forwards(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')

    # Primeiro garante que todos os "raiz" já têm um código válido
    for doc in Documento.objects.filter(documento_original__isnull=True, codigo__isnull=True):
        doc.codigo = uuid.uuid4()
        doc.save(update_fields=['codigo'])

    # Agora propaga o mesmo código para cada revisão derivada
    for doc in Documento.objects.filter(documento_original__isnull=False):
        # se o pai ainda não foi atualizado, sobe uma vez
        if not doc.documento_original.codigo:
            doc.documento_original.codigo = uuid.uuid4()
            doc.documento_original.save(update_fields=['codigo'])

        doc.codigo = doc.documento_original.codigo
        doc.save(update_fields=['codigo'])


def backwards(apps, schema_editor):
    """
    Apenas limpa os códigos gerados – não apaga a coluna, pois o
    schema-migration 0044 a criou.
    """
    Documento = apps.get_model('documentos', 'Documento')
    Documento.objects.update(codigo=None)


class Migration(migrations.Migration):
    dependencies = [
        ('documentos', '0044_alter_documento_options_documento_codigo_and_more'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
