# ia/openai_helper.py
from openai import OpenAI
from django.conf import settings

oa_client = OpenAI()                        
def get_or_create_thread(chat):
    """
    Se o Chat já tem um thread_id, devolve-o.
    Caso contrário cria um novo thread na OpenAI e grava no model.
    """
    if chat.assistant_thread_id:
        return chat.assistant_thread_id

    thread = oa_client.beta.threads.create()
    chat.assistant_thread_id = thread.id
    chat.save(update_fields=["assistant_thread_id"])
    return thread.id


def ensure_oa_file(attachment):
    """
    Faz upload do anexo para a OpenAI apenas uma vez.
    Guarda file_id no metadata do anexo.
    """
    if attachment.metadata and attachment.metadata.get("oa_file_id"):
        return attachment.metadata["oa_file_id"]

    oa_file = oa_client.files.create(
        file=open(attachment.file.path, "rb"),
        purpose="assistants"
    )
    attachment.metadata = {"oa_file_id": oa_file.id}
    attachment.save(update_fields=["metadata"])
    return oa_file.id
