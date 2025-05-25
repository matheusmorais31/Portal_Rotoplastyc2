# documentos/migrations/XXXX_popular_identificador_raiz.py
from django.db import migrations
from django.utils.text import slugify
import uuid

def get_ultimate_original(doc_instance, doc_map):
    """Helper para encontrar o documento original raiz de uma cadeia."""
    current = doc_instance
    visited_ids = {current.id}
    while current.documento_original_id and current.documento_original_id in doc_map:
        parent = doc_map[current.documento_original_id]
        if parent.id in visited_ids: # Ciclo detectado
            # Em caso de ciclo, o 'current' antes de entrar no ciclo é a "raiz" dessa sub-cadeia.
            # No entanto, para esta migração, vamos tratar 'current' como uma raiz se o pai já foi visitado.
            return current # Ou o pai, dependendo da lógica de quebra de ciclo desejada
        visited_ids.add(parent.id)
        current = parent
    return current

def popular_dados_identificador_raiz(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')
    db_alias = schema_editor.connection.alias

    # Carregar todos os documentos para processamento em memória (cuidado com bancos muito grandes)
    # Ordenar por ID pode ajudar a processar raízes antes de suas revisões, mas não é garantido sem lógica explícita.
    all_docs = list(Documento.objects.using(db_alias).order_by('id').all())
    doc_map = {doc.id: doc for doc in all_docs}
    docs_to_update = []

    for doc in all_docs:
        # Se já tiver um identificador_raiz (ex: de uma execução anterior parcial), pule.
        if doc.identificador_raiz:
            continue

        original_raiz = get_ultimate_original(doc, doc_map)

        if not original_raiz.identificador_raiz:
            # Se a raiz da cadeia ainda não tem um identificador, crie um para ela.
            # Usar o nome da raiz original e seu PK para maior unicidade inicial.
            original_raiz.identificador_raiz = f"{slugify(original_raiz.nome)}-{original_raiz.pk}-{uuid.uuid4().hex[:8]}"
            # Adicionamos à lista para atualização em lote ou salvamos individualmente
            # Para evitar problemas com o objeto na doc_map vs. DB, é melhor atualizar o objeto na map também
            # e salvar no final ou em lotes.
            # Documento.objects.using(db_alias).filter(pk=original_raiz.pk).update(identificador_raiz=original_raiz.identificador_raiz)
            # Se for atualizar individualmente, recarregue da doc_map para consistência
            doc_map[original_raiz.id].identificador_raiz = original_raiz.identificador_raiz
            # Adicionar à lista para salvar depois pode ser mais eficiente
            if original_raiz not in docs_to_update:
                 docs_to_update.append(original_raiz)


        # Propaga o identificador da raiz para o documento atual, se for diferente da raiz.
        if doc.id != original_raiz.id:
            doc.identificador_raiz = original_raiz.identificador_raiz
            if doc not in docs_to_update:
                docs_to_update.append(doc)
        elif not doc.identificador_raiz: # Se o doc é a própria raiz e ainda não tem ID
            doc.identificador_raiz = original_raiz.identificador_raiz # Garante que o doc (que é a raiz) tenha o ID
            if doc not in docs_to_update:
                docs_to_update.append(doc)


    # Atualizar todos os documentos modificados
    # Usar update_fields é crucial para não disparar outros saves/signals desnecessariamente
    # e para evitar sobrescrever outros campos que possam ter sido alterados em memória.
    # Django < 2.2 não suporta bulk_update com update_fields facilmente para todos os campos.
    # Iterar e salvar individualmente com update_fields é mais seguro aqui.
    for doc_to_save in docs_to_update:
         # Verifique se o identificador_raiz não é None ou vazio antes de salvar
        if doc_to_save.identificador_raiz:
            Documento.objects.using(db_alias).filter(pk=doc_to_save.pk).update(identificador_raiz=doc_to_save.identificador_raiz)
        else:
            # Fallback para documentos que por algum motivo não receberam um ID (ex: órfãos completos)
            fallback_id = f"fallback-{slugify(doc_to_save.nome)}-{doc_to_save.pk}-{uuid.uuid4().hex[:8]}"
            Documento.objects.using(db_alias).filter(pk=doc_to_save.pk).update(identificador_raiz=fallback_id)


    # Após a migração, o campo não deve mais permitir null=True, blank=True
    # Isso será feito na próxima migração manual ou ajustando o modelo e criando nova migração.

def remover_dados_identificador_raiz(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')
    db_alias = schema_editor.connection.alias
    Documento.objects.using(db_alias).update(identificador_raiz=None)


class Migration(migrations.Migration):
    dependencies = [
        ('documentos', '0041_documento_identificador_raiz_and_more'),
    ]
    operations = [
        migrations.RunPython(popular_dados_identificador_raiz, remover_dados_identificador_raiz),
    ]