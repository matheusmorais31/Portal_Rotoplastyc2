# documentos/management/commands/reindex_ai_docs.py
from django.core.management.base import BaseCommand
from documentos.models import Documento
from ia.views import extract_text_from_file
from ia.retrieval import embed_text
import os, logging

log = logging.getLogger("reindex")

class Command(BaseCommand):
    help = "Re-extrai text_content (e embedding se o campo existir) dos docs aprovados."

    def handle(self, *args, **opts):
        qs = Documento.objects.filter(status="aprovado", is_active=True)
        has_embedding_field = hasattr(Documento, "embedding")

        for doc in qs:
            try:
                path = (
                    doc.documento_pdf.path
                    if doc.documento_pdf else doc.documento.path
                )
                with open(path, "rb") as f:
                    raw = f.read()

                doc.text_content = (
                    extract_text_from_file(os.path.basename(path), raw) or ""
                )[:10_000]

                # só gera embedding se o campo existir
                if has_embedding_field:
                    emb = embed_text(doc.text_content)
                    if emb is not None:
                        doc.embedding = emb
                doc.save(
                    update_fields=[
                        "text_content",
                        *(["embedding"] if has_embedding_field else []),
                    ]
                )
                self.stdout.write(
                    self.style.SUCCESS(f"{doc.id} OK (embedding: {has_embedding_field})")
                )

            except Exception as e:
                log.error(f"{doc.id} ERRO: {e}", exc_info=True)
                self.stderr.write(self.style.ERROR(f"{doc.id} ERRO"))
