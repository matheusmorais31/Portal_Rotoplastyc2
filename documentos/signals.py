from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Documento
from ia.views import extract_text_from_file      # já existe
from ia.retrieval import embed_text              # criaremos já já
import logging, io, os
from django.db.models.signals import pre_save
from .models import Documento, DocumentoNomeHistorico


logger = logging.getLogger("documentos")

@receiver(post_save, sender=Documento)
def index_doc_for_ai(sender, instance: Documento, created, **kwargs):
    # Só indexa se já estiver aprovado, ativo e com arquivo válido
    if instance.status != "aprovado" or not instance.is_active:
        return
    try:
        path = instance.documento_pdf.path if instance.documento_pdf \
               else instance.documento.path
        with open(path, "rb") as f:
            raw = f.read()
        extracted = extract_text_from_file(os.path.basename(path), raw) or ""
        #    limita tamanho para banco (10k chars ≈ 3 pages)
        instance.text_content = extracted[:10_000]
        #  embedding opcional:
        instance.embedding = embed_text(instance.text_content)  # numpy.ndarray
        instance.save(update_fields=["text_content", "embedding"])
        logger.info(f"Documento {instance.id} indexado p/ IA ({len(extracted)} chars).")
    except Exception as e:
        logger.error(f"Falha ao indexar doc {instance.id}: {e}", exc_info=True)

@receiver(pre_save, sender=Documento)
def track_renames(sender, instance: Documento, **kwargs):
    """
    Sempre que `nome` mudar gera um registro em DocumentoNomeHistorico.
    Usa o atributo auxiliar `_rename_user`, que a view `nova_revisao`
    injeta para identificar quem fez a troca.
    """
    # Só interessa em UPDATE (objeto já existe)
    if not instance.pk:
        return

    try:
        antigo = Documento.objects.get(pk=instance.pk)
    except Documento.DoesNotExist:
        return

    if antigo.nome != instance.nome:
        DocumentoNomeHistorico.objects.create(
            documento=instance,
            nome_antigo=antigo.nome,
            nome_novo=instance.nome,
            usuario=getattr(instance, "_rename_user", None),
        )
        logger.info(
            f"Documento {instance.codigo} renomeado de "
            f"'{antigo.nome}' para '{instance.nome}' "
            f"por {getattr(instance, '_rename_user', 'sistema')}."
        )