# ia/views.py

import json
import logging
import traceback
import re # Importar o módulo de regex
import base64
import mimetypes
import io # Para trabalhar com streams de bytes na extração
from django.utils import timezone
import google.generativeai as genai
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from decimal import Decimal
from django import forms
from .models import Chat, ChatMessage, ChatAttachment, ApiUsageLog

# --- Imports das bibliotecas de extração ---
# Guardados por try-except para não quebrar se não instalados
try:
    import docx
except ImportError:
    docx = None
try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    import fitz  # PyMuPDF para extração de PDF
    pymupdf_available = True
except ImportError:
    fitz = None
    pymupdf_available = False
try:
    # Importa as partes necessárias do odfpy
    import odf.opendocument
    import odf.text
    import odf.teletype # Necessário para extractText
    odfpy_available = True
except ImportError:
    odfpy_available = False # Define como False se não estiver instalado

logger = logging.getLogger(__name__)

# --- Configurações e Constantes ---
MAX_UPLOAD_SIZE_MB = getattr(settings, 'MAX_CHAT_UPLOAD_MB', 15)
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
# Limite de caracteres para extração de texto de arquivos
MAX_EXTRACTION_CHARS = getattr(settings, 'IA_MAX_FILE_EXTRACTION_CHARS', 5000)
EMOJI_PATTERN = r"[\U0001F300-\U0001FAFF\U00002700-\U000027B0]"

# Modelos Gemini Mapeados
MODEL_MAP = {
    # 1.5
    "gemini-1.5-pro":   "models/gemini-1.5-pro-latest",
    "gemini-1.5-flash": "models/gemini-1.5-flash-latest",

    # 2.0 (flash & flash-lite) 
    "gemini-2.0-flash":      "models/gemini-2.0-flash",
    "gemini-2.0-flash-lite": "models/gemini-2.0-flash-lite",

    # 2.5 preview
    "gemini-2.5-pro":   "models/gemini-2.5-pro-preview-03-25",
    "gemini-2.5-flash": "models/gemini-2.5-flash-preview-04-17",
}

DEFAULT_GEMINI_MODEL_KEY = "gemini-1.5-flash"
DEFAULT_GEMINI_MODEL_NAME = MODEL_MAP.get(DEFAULT_GEMINI_MODEL_KEY, "models/gemini-1.5-flash-latest")

# Extensões suportadas para extração de texto
EXTRACTABLE_EXTENSIONS = {
    '.pdf', '.docx', '.xlsx', '.odt', '.txt', '.csv', '.md', '.rtf',
    '.py', '.js', '.html', '.css'
}
# Mimetypes de imagem suportados pela API Gemini
SUPPORTED_IMAGE_MIMETYPES_FOR_API = [
    'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/heic', 'image/heif'
]

# Importa a função de cálculo de custo e formulários
try:
    from .cost_calculator import calculate_gemini_cost
except ImportError:
    logger.error("Arquivo ia/cost_calculator.py não encontrado. Cálculo de custo desativado.")
    def calculate_gemini_cost(*args, **kwargs): return Decimal(0)
try:
    from .forms import ApiUsageFilterForm
except ImportError:
    logger.warning("Arquivo ia/forms.py ou ApiUsageFilterForm não encontrado.")
    ApiUsageFilterForm = None

from django.contrib.auth import get_user_model
User = get_user_model()

# --- Configuração da API Gemini ---
try:
    if hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        logger.info("API Key do Gemini configurada com sucesso.")
    else:
        logger.warning("GEMINI_API_KEY não encontrada ou vazia nas configurações.")
except Exception as e:
    logger.error(f"Erro ao configurar a API Key do Gemini: {e}")


# --- Funções Auxiliares ---

def remove_emojis(text):
    """Remove emojis de uma string."""
    if not text or not isinstance(text, str):
        return text
    return re.sub(EMOJI_PATTERN, '', text).strip()

def extract_text_from_file(filename, file_content_bytes):
    # <-- LOG 3: Confirma que a função foi chamada -->
    logger.debug(f"FUNÇÃO extract_text_from_file INICIADA para: '{filename}'")
    """
    Tenta extrair texto de diferentes tipos de arquivo usando bibliotecas apropriadas.
    Retorna o texto extraído (limitado em tamanho) ou uma string de erro/aviso.
    """
    logger.debug(f"Tentando extrair texto de '{filename}' (Tamanho: {len(file_content_bytes)} bytes)")
    ext = '.' + filename.split('.')[-1].lower() if '.' in filename else ''
    text = None
    library_missing = False
    error_message = None # Mensagem específica de erro na extração

    try:
        # --- DOCX ---
        if ext == '.docx':
            if not docx: library_missing = True; raise ImportError("python-docx não está instalado.")
            document = docx.Document(io.BytesIO(file_content_bytes))
            text = "\n".join([para.text for para in document.paragraphs if para.text])

        # --- XLSX ---
        elif ext == '.xlsx':
            if not openpyxl: library_missing = True; raise ImportError("openpyxl não está instalado.")
            workbook = openpyxl.load_workbook(filename=io.BytesIO(file_content_bytes), data_only=True)
            all_texts = []
            max_rows = 100 # Limite de linhas por planilha
            max_cols = 50  # Limite de colunas por linha
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                all_texts.append(f"--- Planilha: {sheet_name} ---")
                for row in sheet.iter_rows(max_row=max_rows):
                    row_texts = [str(cell.value) for cell in row[:max_cols] if cell.value is not None and str(cell.value).strip()]
                    if row_texts:
                        all_texts.append(" | ".join(row_texts))
                if sheet.max_row > max_rows:
                    all_texts.append(f"(...mais {sheet.max_row - max_rows} linhas não incluídas...)")
            text = "\n".join(all_texts)

        # --- PDF (Usando PyMuPDF/fitz) ---
        elif ext == '.pdf':
            logger.debug(f"Processando PDF com PyMuPDF. Biblioteca disponível: {pymupdf_available}") # <-- LOG ADICIONADO
            if not pymupdf_available: library_missing = True; raise ImportError("PyMuPDF (fitz) não está instalado.")
            all_texts = []
            max_pages = 200 # Limite de páginas
            try:
                logger.debug("Tentando abrir PDF com fitz.open()...") # <-- LOG ADICIONADO
                # Use stream= para ler de bytes
                doc = fitz.open(stream=file_content_bytes, filetype="pdf")
                num_pages = len(doc)
                logger.debug(f"PDF aberto com sucesso via PyMuPDF. Número de páginas: {num_pages}") # <-- LOG ADICIONADO
                for i, page in enumerate(doc.pages()):
                    if i >= max_pages:
                        logger.warning(f"Limite de {max_pages} páginas atingido para '{filename}'.") # <-- LOG ADICIONADO
                        all_texts.append(f"\n(...mais {num_pages - max_pages} páginas não incluídas...)")
                        break
                    # Extrai texto ordenado da página
                    page_text = page.get_text("text", sort=True)
                    # Descomente a linha abaixo se precisar de log MUITO detalhado (cuidado com o volume)
                    # logger.debug(f"Texto extraído da página {i+1} (primeiros 100 chars): {page_text[:100]}")
                    if page_text:
                        all_texts.append(page_text)
                doc.close() # Fecha o documento
                text = "\n".join(all_texts)

                if text:
                    logger.info(f"Texto extraído com sucesso via PyMuPDF de '{filename}'.") # <-- LOG ADICIONADO
                else:
                    # Se o documento foi aberto mas não retornou texto
                    logger.warning(f"PyMuPDF (fitz) não extraiu texto do PDF '{filename}'. O arquivo pode estar vazio ou não conter texto reconhecível.")
                    error_message = f"(Não foi possível extrair conteúdo textual de '{filename}')"

            except Exception as pdf_err: # Captura erros específicos do fitz ou gerais na leitura
                logger.error(f"Erro ao processar PDF '{filename}' com PyMuPDF (fitz): {pdf_err}", exc_info=True) # <-- LOG DE ERRO IMPORTANTE
                error_message = f"(Erro ao tentar processar o arquivo PDF '{filename}')"


        # --- ODT (Usando odfpy) ---
        elif ext == '.odt':
            if not odfpy_available: library_missing = True; raise ImportError("odfpy não está instalado.")
            try:
                doc = odf.opendocument.load(io.BytesIO(file_content_bytes))
                all_texts = []
                text_elements = doc.getElementsByType(odf.text.P) # Parágrafos
                for elem in text_elements:
                    para_text = odf.teletype.extractText(elem)
                    if para_text:
                        all_texts.append(para_text.strip())
                text = "\n".join(all_texts)
                if not text:
                    logger.warning(f"odfpy não extraiu texto do ODT '{filename}'. Documento vazio ou estrutura incomum?")
                    error_message = f"(Não foi possível extrair conteúdo textual de '{filename}')"
            except Exception as odf_err:
                logger.error(f"Erro ao processar ODT '{filename}' com odfpy: {odf_err}", exc_info=True)
                error_message = f"(Erro ao processar o arquivo ODT '{filename}')"

        # --- Tipos baseados em Texto Simples ---
        elif ext in EXTRACTABLE_EXTENSIONS: # Pega outros da lista (txt, csv, etc.)
            try:
                text = file_content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                logger.warning(f"Falha ao decodificar '{filename}' como UTF-8, tentando latin-1.")
                try:
                    text = file_content_bytes.decode('latin-1', errors='replace')
                except Exception as decode_err:
                     logger.error(f"Falha ao decodificar '{filename}' como latin-1 também: {decode_err}")
                     error_message = f"(Não foi possível decodificar o conteúdo de '{filename}')"

        # --- Não Suportado ---
        else:
            logger.warning(f"Extração de texto não suportada para extensão '{ext}' do arquivo '{filename}'.")
            # Retorna None para indicar que não é um tipo extraível

        # --- Processamento Final do Texto Extraído ---
        if text:
            original_len = len(text)
            if original_len > MAX_EXTRACTION_CHARS:
                text = text[:MAX_EXTRACTION_CHARS] + f"\n\n(... [CONTEÚDO TRUNCADO em {MAX_EXTRACTION_CHARS} caracteres] ...)"
                logger.info(f"Texto extraído de '{filename}' (ext: {ext}) TRUNCADO para {MAX_EXTRACTION_CHARS} caracteres (original: {original_len}).")
            else:
                logger.info(f"Texto extraído com sucesso de '{filename}' (ext: {ext}, {original_len} caracteres).")
            # Limpa espaços extras e linhas vazias
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            return text # Retorna o texto processado

        elif error_message:
            # Se houve um erro específico durante a extração
             return error_message
        elif not library_missing and ext in ['.docx', '.xlsx', '.pdf', '.odt']:
             # Se a biblioteca existe mas não extraiu texto e não houve erro específico
             logger.warning(f"Biblioteca para '{ext}' foi encontrada, mas não retornou texto de '{filename}'.")
             return f"(Não foi possível extrair conteúdo textual de '{filename}')"
        else:
            # Se não era um tipo extraível ou houve outro problema não capturado
            return None # Indica falha ou não aplicável

    except ImportError as ie:
        logger.error(f"Erro de importação ao tentar processar '{filename}' (ext: {ext}): {ie}. Verifique se a biblioteca está instalada.")
        return f"(Erro: Biblioteca para processar arquivos '{ext}' não encontrada no servidor.)"
    except Exception as e:
        logger.error(f"Erro inesperado ao extrair texto de '{filename}' (ext: {ext}): {e}", exc_info=True)
        # Retorna mensagem de erro genérica, evitando expor detalhes internos
        return f"(Erro ao tentar ler o conteúdo de '{filename}')"

def log_api_usage(user, model_name, ai_message, usage_metadata, image_count):
    """Tenta registrar o uso da API e calcular o custo em USD e BRL."""
    if not usage_metadata:
        logger.warning(f"Metadados de uso não encontrados para msg {ai_message.id if ai_message else '?'}. Custo não registrado.")
        return

    try:
        input_tokens = getattr(usage_metadata, 'prompt_token_count', 0)
        output_tokens = getattr(usage_metadata, 'candidates_token_count', 0)

        # Calcula o custo estimado em USD
        estimated_cost_usd = calculate_gemini_cost(
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_count=image_count
        )

        # Converte para BRL
        usd_to_brl_rate = getattr(settings, 'USD_TO_BRL_RATE', None)
        estimated_cost_brl = Decimal('0.0')

        if usd_to_brl_rate:
             try:
                 rate = Decimal(str(usd_to_brl_rate))
                 if rate > 0:
                     estimated_cost_brl = estimated_cost_usd * rate
                 else:
                      logger.error(f"USD_TO_BRL_RATE ('{usd_to_brl_rate}') inválida (não positiva). Custo BRL não calculado.")
             except (ValueError, TypeError):
                  logger.error(f"USD_TO_BRL_RATE ('{usd_to_brl_rate}') inválida (não é número). Custo BRL não calculado.")
        else:
             logger.warning("USD_TO_BRL_RATE não definida nas configurações. Custo BRL não calculado.")


        # Cria e salva o registro de log
        log_entry = ApiUsageLog.objects.create(
            user=user,
            model_name=model_name,
            ai_message=ai_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_count=image_count,
            estimated_cost=estimated_cost_usd,
            estimated_cost_brl=estimated_cost_brl,
            timestamp=ai_message.created_at if ai_message else timezone.now()
        )
        logger.info(f"Uso API registrado: Log {log_entry.id}, User: {user.username}, Model: {model_name}, "
                    f"Tokens In: {input_tokens}, Out: {output_tokens}, Imgs: {image_count}, "
                    f"Cost: ${estimated_cost_usd:.6f} / R${estimated_cost_brl:.6f}")

    except AttributeError as ae:
        logger.error(f"Erro ao acessar atributos usage_metadata para msg {ai_message.id if ai_message else '?'}: {ae}. Metadados: {usage_metadata}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro ao registrar log de uso API para msg {ai_message.id if ai_message else '?'}: {e}", exc_info=True)


# --- Views ---

@login_required
def chat_page_view(request):
    """Renderiza a página do chat (HTML)."""
    api_key_configured = bool(hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY)
    context = {
        'api_key_configured': api_key_configured
    }
    return render(request, 'ia/chat_page.html', context)

@login_required
@csrf_exempt
@require_http_methods(["GET"])
def list_chats_view(request):
    """Lista todas as conversas do usuário logado, garantindo retorno JSON."""
    user = request.user
    try:
        chats = Chat.objects.filter(user=user).order_by('-updated_at')
        data = [{
                 'id': chat.id,
                 'title': str(chat.title) if chat.title else f"Chat {chat.id}",
                 'created_at': chat.created_at.isoformat() if chat.created_at else None,
                 'updated_at': chat.updated_at.isoformat() if chat.updated_at else None,
             } for chat in chats]
        return JsonResponse(data, safe=False)
    except Exception as e:
        logger.error(f"Erro ao listar chats para {user.username}: {e}", exc_info=True)
        return JsonResponse({'error': 'Erro interno ao buscar lista de chats.'}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def create_chat_view(request):
    """Cria uma nova conversa para o usuário logado."""
    user = request.user
    try:
        title = 'Nova Conversa'
        new_chat = Chat.objects.create(user=user, title=title)
        logger.info(f"Chat {new_chat.id} ('{new_chat.title}') criado para usuário {user.username}.")
        return JsonResponse({
            'id': new_chat.id,
            'title': new_chat.title,
            'created_at': new_chat.created_at.isoformat(),
            'updated_at': new_chat.updated_at.isoformat(),
        }, status=201)
    except Exception as e:
        logger.exception(f"Erro ao criar nova conversa para {user.username}: {e}")
        return JsonResponse({'error': 'Erro interno ao criar nova conversa.'}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["GET"])
def get_chat_view(request, chat_id):
    """Retorna os detalhes de um chat específico do usuário, incluindo mensagens e anexos."""
    user = request.user
    try:
        chat = get_object_or_404(Chat, id=chat_id, user=user)
        messages_qs = chat.messages.order_by('created_at').prefetch_related('attachments')

        messages_data = []
        for msg in messages_qs:
            msg_attachments_data = []
            for att in msg.attachments.all():
                try:
                    msg_attachments_data.append({
                        'id': att.id,
                        'url': att.file.url,
                        'filename': att.get_filename()
                    })
                except Exception as att_err:
                    logger.error(f"Erro ao processar anexo {att.id} para msg {msg.id} no chat {chat_id}: {att_err}")

            messages_data.append({
                'id': msg.id,
                'sender': msg.sender,
                'text': msg.text,
                'created_at': msg.created_at.isoformat(),
                'attachments': msg_attachments_data
            })

        return JsonResponse({
            'id': chat.id,
            'title': chat.title,
            'messages': messages_data,
            'created_at': chat.created_at.isoformat(),
            'updated_at': chat.updated_at.isoformat(),
        })
    except Chat.DoesNotExist:
        return JsonResponse({'error': 'Chat não encontrado ou não pertence a este usuário.'}, status=404)
    except Exception as e:
        logger.exception(f"Erro ao buscar chat {chat_id} para user {user.username}: {e}")
        return JsonResponse({'error': 'Erro interno ao buscar dados do chat.'}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_chat_view(request, chat_id):
    """Exclui uma conversa inteira do usuário logado."""
    user = request.user
    try:
        chat = get_object_or_404(Chat, id=chat_id, user=user)
        chat_title = chat.title
        chat_id_log = chat.id
        chat.delete()
        logger.info(f"Chat {chat_id_log} ('{chat_title}') excluído pelo usuário {user.username}.")
        return JsonResponse({'status': 'deleted', 'message': f'Chat "{chat_title}" excluído com sucesso.'})
    except Chat.DoesNotExist:
        return JsonResponse({'error': 'Chat não encontrado ou não pertence a este usuário.'}, status=404)
    except Exception as e:
        logger.exception(f"Erro ao excluir chat {chat_id} pelo usuário {user.username}: {e}")
        return JsonResponse({'error': 'Erro interno ao excluir o chat.'}, status=500)


# ==============================================================================
# == VIEW COMBINADA: Enviar Mensagem (Texto e/ou Arquivos) para a IA ==
# ==============================================================================
@login_required
@csrf_exempt
@require_http_methods(["POST"])
def send_message_view(request, chat_id):
    """
    Recebe texto (prompt) e/ou arquivos via FormData,
    processa (extraindo texto de documentos), salva anexos,
    envia para a API Gemini, registra o uso e retorna a resposta.
    """
    # ───────── 0. Sanidade inicial e Recuperação do Chat ─────────
    if not (hasattr(settings, "GEMINI_API_KEY") and settings.GEMINI_API_KEY):
        logger.error("Tentativa de chamada à API Gemini sem GEMINI_API_KEY configurada.")
        return JsonResponse({"error": "A configuração da API do serviço de IA está indisponível."}, status=503)

    user = request.user
    try:
        chat = get_object_or_404(Chat, id=chat_id, user=user)
    except Chat.DoesNotExist:
        return JsonResponse({'error': 'Chat não encontrado ou acesso não permitido.'}, status=404)
    except Exception as e:
        logger.error(f"Erro inesperado ao buscar chat {chat_id} para user {user.username}: {e}", exc_info=True)
        return JsonResponse({'error': 'Erro interno ao buscar chat.'}, status=500)

    logger.info(f"Iniciando processamento de mensagem para chat {chat.id} (user: {user.username})")

    # ───────── 1. Processar Texto do Prompt (do FormData) ─────────
    prompt_raw = request.POST.get("prompt", "").strip()
    prompt_user_typed = remove_emojis(prompt_raw)
    logger.debug(f"Prompt recebido (raw): '{prompt_raw[:100]}...', (limpo): '{prompt_user_typed[:100]}...'")
    if not prompt_user_typed and prompt_raw:
        logger.warning(f"Prompt para chat {chat.id} continha apenas emojis e foi removido.")

    # ───────── 2. Processar Arquivos (Imagens e Documentos do FormData) ─────────
    image_parts_for_api = []
    saved_attachments = []
    extracted_content = {}
    upload_errors = []
    files_received = request.FILES.getlist('arquivo')
    image_count_for_log = 0

    if files_received:
        logger.info(f"Recebidos {len(files_received)} arquivo(s) para processar no chat {chat.id}.")
        for uploaded_file in files_received:
            original_filename = uploaded_file.name
            attachment = None
            is_image_for_api = False
            is_extractable_document = False

            try:
                # Validação de Tamanho
                if uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
                    raise ValueError(f"Arquivo '{original_filename}' ({uploaded_file.size / (1024*1024):.2f}MB) excede o limite de {MAX_UPLOAD_SIZE_MB}MB.")

                # Identificação de Tipo
                mime_type, _ = mimetypes.guess_type(original_filename)
                file_ext = '.' + original_filename.split('.')[-1].lower() if '.' in original_filename else ''

                # É imagem para API?
                if mime_type and mime_type in SUPPORTED_IMAGE_MIMETYPES_FOR_API:
                    is_image_for_api = True
                    uploaded_file.seek(0)
                    image_bytes = uploaded_file.read()
                    encoded_image = base64.b64encode(image_bytes).decode('utf-8')
                    image_parts_for_api.append({
                        "inline_data": {"mime_type": mime_type, "data": encoded_image}
                    })
                    image_count_for_log += 1
                    logger.info(f"Imagem '{original_filename}' preparada para API.")

                # É um documento do qual tentaremos extrair texto?
                elif file_ext in EXTRACTABLE_EXTENSIONS:
                    is_extractable_document = True
                    logger.info(f"Arquivo '{original_filename}' (ext: {file_ext}) será processado para extração de texto.")

                # Tipo não suportado
                else:
                     raise ValueError(f"Tipo de arquivo (ext: {file_ext}, mime: {mime_type or 'desconhecido'}) não é suportado.")

                # Salva o anexo (se for imagem ou documento extraível)
                attachment = ChatAttachment(chat=chat, file=uploaded_file)
                attachment.save()
                saved_attachments.append(attachment)
                logger.info(f"Anexo '{original_filename}' (ID: {attachment.id}) salvo.")

                # ** EXTRAÇÃO DE TEXTO (se aplicável) **
                if is_extractable_document:
                    # <-- LOG 1: Confirma que o arquivo foi marcado como extraível -->
                    logger.debug(f"Arquivo '{original_filename}' identificado como extraível (ext='{file_ext}'). Tentando ler bytes e chamar extract_text_from_file.")
                    try:
                        uploaded_file.seek(0)
                        file_content_bytes = uploaded_file.read()
                        # <-- LOG 2: Verifica se os bytes foram lidos -->
                        logger.debug(f"Bytes lidos para '{original_filename}': {len(file_content_bytes)} bytes.")
                        if file_content_bytes:
                             # Chama a função de extração atualizada
                             extracted_text = extract_text_from_file(original_filename, file_content_bytes) # A chamada acontece aqui
                             extracted_content[original_filename] = extracted_text
                        else:
                             logger.warning(f"Não foi possível ler bytes de '{original_filename}' antes da extração.")
                             extracted_content[original_filename] = f"(Erro ao ler o arquivo '{original_filename}' antes da extração)"

                    except Exception as extraction_error:
                        logger.error(f"Erro crítico durante chamada de extração para {original_filename}: {extraction_error}", exc_info=True)
                        extracted_content[original_filename] = f"(Erro interno ao tentar ler {original_filename})"

            except ValueError as ve:
                logger.warning(f"Erro de validação para arquivo '{original_filename}' no chat {chat.id}: {ve}")
                upload_errors.append({'filename': original_filename, 'error': str(ve)})
            except Exception as file_proc_err:
                logger.error(f"Erro inesperado ao processar arquivo '{original_filename}' para chat {chat.id}: {file_proc_err}", exc_info=True)
                upload_errors.append({'filename': original_filename, 'error': 'Erro interno ao processar o arquivo.'})
                if attachment and attachment.pk:
                    try: attachment.delete(); logger.warning(f"Anexo {attachment.pk} removido devido a erro.")
                    except Exception as del_err: logger.error(f"Erro adicional ao remover anexo {attachment.pk}: {del_err}")


    # ───────── 3. Validação Mínima e Salvamento da Mensagem + Associação de Anexos ─────────
    if not prompt_user_typed and not image_parts_for_api and not saved_attachments:
        logger.warning(f"Tentativa de envio para chat {chat.id} sem texto e sem arquivos válidos.")
        return JsonResponse({
            "error": 'É necessário enviar um texto ou pelo menos um arquivo suportado.',
            "upload_errors": upload_errors
        }, status=400)

    user_msg = None
    user_attachments_data = []
    try:
        # Salva a mensagem APENAS com o texto que o usuário digitou
        user_msg = ChatMessage.objects.create(chat=chat, sender="user", text=prompt_user_typed)
        if saved_attachments:
            for att in saved_attachments:
                att.message = user_msg
                att.save(update_fields=['message'])
                user_attachments_data.append({
                    'id': att.id,
                    'url': att.file.url,
                    'filename': att.get_filename()
                })
        logger.info(f"Mensagem usuário {user_msg.id} e {len(saved_attachments)} anexos associados salvos.")
    except Exception as e:
        logger.error(f"Erro ao salvar mensagem de usuário ou associar anexos para chat {chat.id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Erro interno ao salvar sua mensagem ou anexos.'}, status=500)

    # ───────── 4. Montar Histórico e Prompt Atual para API ─────────
    history_for_api = []
    try:
        # Pega mensagens anteriores
        previous_messages = chat.messages.filter(created_at__lt=user_msg.created_at).order_by("created_at")
        for msg in previous_messages:
            history_for_api.append({
                "role": "user" if msg.sender == "user" else "model",
                "parts": [{"text": msg.text or ""}] # Apenas texto do histórico
            })
        logger.debug(f"Histórico anterior ({len(history_for_api)} turnos) montado para chat {chat.id}.")
    except Exception as e:
        logger.error(f"Erro ao montar histórico anterior para chat {chat.id}: {e}", exc_info=True)

    # Montar Parts da Mensagem ATUAL
    current_prompt_parts = []
    # 1. Adiciona IMAGENS (se houver)
    if image_parts_for_api:
        current_prompt_parts.extend(image_parts_for_api)

    # 2. Constrói o TEXTO final para a API (prompt + conteúdo extraído)
    final_text_for_api = prompt_user_typed
    if extracted_content:
        final_text_for_api += "\n\n--- Conteúdo dos Arquivos Anexados ---\n"
        for filename, content in extracted_content.items():
            if content: # Inclui texto extraído ou mensagem de erro da extração
                final_text_for_api += f"\n[Conteúdo de: {filename}]\n{content}\n[Fim de: {filename}]\n"
            else:
                # Informa que não foi possível extrair texto deste arquivo específico
                 final_text_for_api += f"\n[Não foi possível extrair texto de: {filename}]\n"
        final_text_for_api += "\n--- Fim do Conteúdo dos Arquivos ---"


    # Adiciona a parte de texto final (mesmo se vazia, se não houver imagens/outros)
    if final_text_for_api or not current_prompt_parts:
        current_prompt_parts.append({"text": final_text_for_api})

    # Verifica se há algo para enviar
    if not current_prompt_parts:
         logger.error(f"Erro crítico: Nenhuma parte para enviar no turno atual (Chat {chat.id}). Texto final era '{final_text_for_api}'. Imagens API: {len(image_parts_for_api)}")
         # Adiciona uma mensagem de erro suave se tudo falhar
         current_prompt_parts.append({"text": "(Não foi possível processar o conteúdo enviado)"})
         # Não retorna erro aqui, tenta enviar essa mensagem fallback

    history_for_api.append({"role": "user", "parts": current_prompt_parts})

    # Adicionar Instrução de Linguagem e Anti-Emoji (tentativa)
    system_instruction = "Responda sempre em português do Brasil. Não use emojis. Analise o conteúdo dos arquivos anexados (indicados por [Conteúdo de:...]), se houver, para formular sua resposta."
    try:
        if history_for_api and history_for_api[-1].get("role") == "user":
            parts = history_for_api[-1].get("parts", [])
            text_part_index = -1
            for i in range(len(parts) -1, -1, -1):
                if "text" in parts[i]:
                    text_part_index = i
                    break
            if text_part_index != -1:
                 original_text = parts[text_part_index].get("text", "") or ""
                 parts[text_part_index]["text"] = f"{original_text}\n\n(Instrução: {system_instruction})"
                 logger.debug(f"Instrução adicionada ao text part existente.")
            else:
                 parts.append({"text": f"(Instrução: {system_instruction})"})
                 logger.debug(f"Instrução adicionada como novo text part.")
        else: logger.warning("Não foi possível adicionar instrução: Histórico vazio ou último turno não é do usuário.")
    except Exception as instr_err:
        logger.error(f"Erro ao tentar adicionar instrução de sistema: {instr_err}")


    # ───────── 5. Mapear Modelo e Chamar API Gemini ─────────
    selected_model_key = request.POST.get("model", DEFAULT_GEMINI_MODEL_KEY)
    model_name = MODEL_MAP.get(selected_model_key, DEFAULT_GEMINI_MODEL_NAME)
    if model_name != MODEL_MAP.get(selected_model_key):
        logger.warning(f"Modelo '{selected_model_key}' não mapeado, usando fallback '{model_name}' para chat {chat.id}.")
    logger.debug(f"Modelo selecionado para API Gemini: {model_name}")

    ai_text_raw = "(Erro: A IA não conseguiu gerar uma resposta.)"
    ai_text = ai_text_raw
    ai_msg = None
    gemini_resp = None

    try:
        model = genai.GenerativeModel(model_name)
        generation_config = genai.types.GenerationConfig(temperature=0.7)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]

        logger.debug(f"Enviando request para Gemini (modelo: {model_name}). Turno atual tem {len(image_parts_for_api)} imagem(ns) API e {len(extracted_content)} arquivo(s) com texto extraído/processado.")
        # Log mais detalhado do payload (cuidado com dados sensíveis)
        # logger.debug(f"Payload (histórico) para Gemini (simplificado): {json.dumps(history_for_api, indent=2, ensure_ascii=False)}")


        # <<< CHAMA A API >>>
        gemini_resp = model.generate_content(
            history_for_api,
            generation_config=generation_config,
            safety_settings=safety_settings
        )

        # Processamento da Resposta da API
        try:
            if hasattr(gemini_resp, 'text') and gemini_resp.text:
                ai_text_raw = gemini_resp.text.strip()
            elif hasattr(gemini_resp, 'candidates') and gemini_resp.candidates and hasattr(gemini_resp.candidates[0], 'content') and gemini_resp.candidates[0].content.parts:
                # Tenta obter texto da estrutura de 'candidates' se .text falhar
                 ai_text_raw = "".join(part.text for part in gemini_resp.candidates[0].content.parts if hasattr(part, 'text')).strip()
                 if not ai_text_raw: # Verifica se ainda assim ficou vazio
                    if gemini_resp.prompt_feedback and gemini_resp.prompt_feedback.block_reason:
                         block_reason = gemini_resp.prompt_feedback.block_reason.name
                         logger.warning(f"Resposta da IA bloqueada (Chat {chat.id}). Razão: {block_reason}")
                         ai_text_raw = f"(A resposta foi bloqueada por segurança: {block_reason})"
                    else:
                         logger.warning(f"Resposta da IA via 'candidates' vazia (Chat {chat.id}). Resposta completa: {gemini_resp}")
                         ai_text_raw = "(A IA retornou uma resposta vazia ou inválida.)"

            elif gemini_resp.prompt_feedback and gemini_resp.prompt_feedback.block_reason:
                 block_reason = gemini_resp.prompt_feedback.block_reason.name
                 logger.warning(f"Resposta da IA bloqueada (Chat {chat.id}). Razão: {block_reason}")
                 ai_text_raw = f"(A resposta foi bloqueada por segurança: {block_reason})"
            else:
                 logger.warning(f"Resposta da IA vazia ou sem texto/candidates válidos (Chat {chat.id}). Resposta: {gemini_resp}")
                 ai_text_raw = "(A IA retornou uma resposta vazia ou inválida.)"

            ai_text = remove_emojis(ai_text_raw)
            if not ai_text and ai_text_raw:
                logger.warning(f"Resposta da IA para chat {chat.id} continha apenas emojis e foi removida.")
                ai_text = "(A resposta da IA continha apenas emojis.)"
            elif not ai_text: # Se remove_emojis resultou em vazio
                ai_text = "(A IA retornou uma resposta vazia.)" # Mantém a mensagem de vazio

        except ValueError as ve: # Captura erro de bloqueio se response.text falhar
            logger.warning(f"ValueError ao processar resposta da IA (provável bloqueio) para chat {chat.id}: {ve}. Feedback: {getattr(gemini_resp, 'prompt_feedback', 'N/A')}")
            ai_text_raw = f"(A resposta foi bloqueada ou interrompida: {ve})"
            ai_text = ai_text_raw # Mantém a mensagem de erro
        except Exception as generic_resp_err:
            logger.error(f"Erro genérico ao processar a resposta da IA para chat {chat.id}: {generic_resp_err}", exc_info=True)
            ai_text_raw = f"(Erro interno ao processar a resposta da IA: {type(generic_resp_err).__name__})"
            ai_text = ai_text_raw # Mantém a mensagem de erro

    except Exception as api_err:
        logger.error(f"Falha crítica na chamada da API Gemini (Chat {chat.id}, modelo: {model_name}): {api_err}", exc_info=True)
        error_type_name = type(api_err).__name__
        ai_text = f"(Erro na comunicação com o serviço de IA: {error_type_name})"
        # Retorna erro 502/503 - NÃO logar custo aqui
        return JsonResponse({
            "error": ai_text,
            "user_message_id": user_msg.id if user_msg else None,
            "user_attachments": user_attachments_data,
            "response": ai_text, # Retorna o erro aqui também
            "ai_message_id": None,
            "upload_errors": upload_errors
        }, status=502) # Bad Gateway or 503 Service Unavailable

    # ───────── 6. Salvar Resposta da IA E LOGAR USO ─────────
    try:
        ai_msg = ChatMessage.objects.create(chat=chat, sender="ai", text=ai_text)
        logger.debug(f"Mensagem da IA (ID: {ai_msg.id}, Texto: '{ai_text[:50]}...') salva para chat {chat.id}.")

        # LOGAR USO DA API
        if gemini_resp and hasattr(gemini_resp, 'usage_metadata'):
             log_api_usage(
                 user=user,
                 model_name=model_name,
                 ai_message=ai_msg,
                 usage_metadata=gemini_resp.usage_metadata,
                 image_count=image_count_for_log # Loga apenas imagens enviadas à API
             )
        elif gemini_resp:
             logger.warning(f"Resposta Gemini para msg {ai_msg.id} não continha 'usage_metadata'. Custo não registrado.")

    except Exception as e:
        logger.error(f"Erro ao salvar mensagem da IA ou logar uso para chat {chat.id}: {e}", exc_info=True)
        # A resposta da IA foi recebida, mas não pôde ser salva. Retorna a resposta mas com erro.
        return JsonResponse({
            'error': 'Erro interno ao salvar a resposta da IA ou registrar uso.',
            'user_message_id': user_msg.id if user_msg else None,
            'user_attachments': user_attachments_data,
            'response': ai_text, # Retorna o texto que deveria ter sido salvo
            'ai_message_id': None, # Indica que não foi salvo
            "upload_errors": upload_errors
        }, status=500)

    # ───────── 7. Gerar Título (Opcional) ─────────
    generated_title = None
    try:
        message_count = chat.messages.count()
        is_default_title = chat.title is None or chat.title.strip().lower().startswith("nova conversa")

        # Tenta gerar título a partir do texto do usuário se for a primeira msg real
        if message_count <= 2 and is_default_title and prompt_user_typed:
             logger.info(f"Tentando gerar título via fallback para chat {chat.id}.")
             words = prompt_user_typed.split()
             fallback_title_raw = " ".join(words[:5])
             if fallback_title_raw:
                 fallback_title_cleaned = re.sub(r"[.!?,;:]$", "", fallback_title_raw).strip().strip('"\'')
                 fallback_title = remove_emojis(fallback_title_cleaned)
                 if fallback_title and len(fallback_title) > 1:
                     generated_title = fallback_title[0].upper() + fallback_title[1:]
                     logger.info(f"Título fallback gerado para chat {chat.id}: '{generated_title}'")
                 else: logger.warning(f"Título fallback gerado para chat {chat.id} resultou vazio.")
             else: logger.warning(f"Não foi possível gerar título fallback para chat {chat.id}.")
    except Exception as title_err:
        logger.error(f"Erro durante a geração de título fallback para chat {chat.id}: {title_err}", exc_info=True)


    # ───────── 8. Atualizar Chat e Preparar Resposta Final ─────────
    fields_to_update = ["updated_at"]
    chat.updated_at = ai_msg.created_at if ai_msg and ai_msg.created_at else timezone.now()
    if generated_title:
        chat.title = generated_title
        fields_to_update.append("title")

    try:
        chat.save(update_fields=fields_to_update)
        logger.debug(f"Chat {chat.id} salvo. Campos atualizados: {fields_to_update}")
    except Exception as final_save_err:
        logger.error(f"Erro ao salvar campos finais ({fields_to_update}) do chat {chat.id}: {final_save_err}")

    resp_data = {
        "response": ai_text,
        "user_message_id": user_msg.id if user_msg else None,
        "ai_message_id": ai_msg.id if ai_msg else None,
        "user_attachments": user_attachments_data,
        "upload_errors": upload_errors
    }
    if "title" in fields_to_update and generated_title:
        resp_data["new_title"] = generated_title

    final_status_code = 207 if upload_errors else 200
    logger.info(f"Processamento concluído para chat {chat.id}. Status: {final_status_code}. Anexos user: {len(user_attachments_data)}. Erros upload: {len(upload_errors)}")
    return JsonResponse(resp_data, status=final_status_code)

# ==============================================================================
# == FIM DA VIEW COMBINADA ==
# ==============================================================================


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def edit_user_message_view(request, chat_id, message_id):
    """
    Edita uma mensagem DO USUÁRIO (apenas texto), remove mensagens posteriores,
    reprocessa a IA (SEM re-extrair anexos), registra o uso e retorna status.
    NOTA: A edição de mensagens que *originalmente* tinham anexos NÃO é suportada.
    """
    user = request.user
    try:
        chat = get_object_or_404(Chat, id=chat_id, user=user)
    except Chat.DoesNotExist:
        return JsonResponse({'error': 'Chat não encontrado ou acesso não permitido.'}, status=404)

    try:
        body = json.loads(request.body)
        new_text_raw = body.get('new_text')
        if not new_text_raw or not isinstance(new_text_raw, str) or not new_text_raw.strip():
            return JsonResponse({'error': 'O novo texto ("new_text") é obrigatório.'}, status=400)

        # Limpa texto e valida
        new_text = remove_emojis(new_text_raw.strip())
        if not new_text:
            return JsonResponse({'error': 'O texto editado não pode ficar vazio ou conter apenas emojis.'}, status=400)

        # Encontra a mensagem e verifica se tem anexos
        msg_to_edit = get_object_or_404(ChatMessage, id=message_id, chat=chat, sender='user')

        # RESTRIÇÃO: Não permite editar mensagens com anexos
        if msg_to_edit.attachments.exists():
             logger.warning(f"Tentativa de editar msg {message_id} com anexos (Chat {chat.id}). Não suportado.")
             return JsonResponse({'error': 'Não é possível editar mensagens que contenham anexos.'}, status=400)

        # Verifica se houve mudança
        if msg_to_edit.text == new_text:
            logger.info(f"Edição da msg {message_id} (Chat {chat.id}) cancelada: texto idêntico.")
            return JsonResponse({'status': 'no_change', 'message': 'Nenhuma alteração necessária.'})

        original_created_at = msg_to_edit.created_at

        # Atualiza o texto da mensagem do usuário
        msg_to_edit.text = new_text
        msg_to_edit.save(update_fields=['text'])
        logger.info(f"Usuário {user.username} editou msg {message_id} (novo texto: '{new_text[:50]}...') no chat {chat_id}.")

        # Remove mensagens posteriores
        subsequent_msgs = chat.messages.filter(created_at__gt=original_created_at)
        deleted_count, deleted_details = subsequent_msgs.delete()
        if deleted_count > 0:
            logger.info(f"{deleted_count} mensagens posteriores ({deleted_details}) deletadas após edição da msg {message_id} no chat {chat_id}.")

        # Monta histórico para reprocessamento (até a msg editada, SEM anexos)
        current_history = []
        for msg in chat.messages.filter(created_at__lte=original_created_at).order_by('created_at'):
            current_history.append({
                'role': 'user' if msg.sender == 'user' else 'model',
                'parts': [{'text': msg.text or ""}] # Apenas texto
            })

        # Adiciona instrução de idioma e anti-emoji
        if current_history and current_history[-1]["role"] == "user":
            instruction = "\n\n(Instruções Importantes: Responda sempre em português brasileiro. NÃO use emojis.)"
            try:
                if current_history[-1].get("parts") and isinstance(current_history[-1]["parts"], list) and len(current_history[-1]["parts"]) > 0:
                    last_part_index = -1
                    for i in range(len(current_history[-1]["parts"]) -1, -1, -1):
                         if "text" in current_history[-1]["parts"][i]: last_part_index = i; break
                    if last_part_index != -1:
                        current_history[-1]["parts"][last_part_index]["text"] = (current_history[-1]["parts"][last_part_index].get("text", "") or "") + instruction
                    else: current_history[-1]["parts"].append({"text": instruction.strip()})
                else: current_history[-1]["parts"] = [{"text": instruction.strip()}]
                logger.debug(f"Instruções adicionadas ao histórico pós-edição (Chat {chat.id}).")
            except Exception as instr_err:
                logger.error(f"Erro ao adicionar instruções pós-edição (Chat {chat.id}): {instr_err}", exc_info=True)

        # Seleciona modelo e Reprocessa com a IA
        selected_model_key = body.get('model', DEFAULT_GEMINI_MODEL_KEY)
        model_name = MODEL_MAP.get(selected_model_key, DEFAULT_GEMINI_MODEL_NAME)
        logger.debug(f"Reprocessando com modelo {model_name} para chat {chat_id} após edição da msg {message_id}.")

        new_ai_response_text = "(Erro ao reprocessar IA após edição)"
        new_ai_message = None
        gemini_resp_edit = None

        try:
            model = genai.GenerativeModel(model_name)
            generation_config = genai.types.GenerationConfig(temperature=0.7)
            safety_settings = [
                 {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                 {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             ]
            # <<< CHAMA A API (Apenas com histórico de texto) >>>
            gemini_resp_edit = model.generate_content(
                current_history,
                generation_config=generation_config,
                safety_settings=safety_settings
            )

            # Processa resposta da IA (similar a send_message_view)
            new_ai_response_text_raw = ""
            try:
                if hasattr(gemini_resp_edit, 'text') and gemini_resp_edit.text:
                    new_ai_response_text_raw = gemini_resp_edit.text.strip()
                elif hasattr(gemini_resp_edit, 'candidates') and gemini_resp_edit.candidates and hasattr(gemini_resp_edit.candidates[0], 'content') and gemini_resp_edit.candidates[0].content.parts:
                     new_ai_response_text_raw = "".join(part.text for part in gemini_resp_edit.candidates[0].content.parts if hasattr(part, 'text')).strip()
                     if not new_ai_response_text_raw:
                         if gemini_resp_edit.prompt_feedback and gemini_resp_edit.prompt_feedback.block_reason:
                              block_reason = gemini_resp_edit.prompt_feedback.block_reason.name
                              new_ai_response_text_raw = f"(A nova resposta foi bloqueada: {block_reason})"
                         else: new_ai_response_text_raw = "(A IA retornou uma resposta vazia após edição.)"
                elif gemini_resp_edit.prompt_feedback and gemini_resp_edit.prompt_feedback.block_reason:
                    block_reason = gemini_resp_edit.prompt_feedback.block_reason.name
                    new_ai_response_text_raw = f"(A nova resposta foi bloqueada: {block_reason})"
                else:
                    new_ai_response_text_raw = "(A IA retornou uma resposta vazia após edição.)"

                new_ai_response_text = remove_emojis(new_ai_response_text_raw)
                if not new_ai_response_text and new_ai_response_text_raw: new_ai_response_text = "(Resposta da IA continha apenas emojis.)"
                elif not new_ai_response_text: new_ai_response_text = "(A IA retornou uma resposta vazia após edição.)"

            except ValueError as ve: # Bloqueio
                new_ai_response_text_raw = f"(A nova resposta foi bloqueada: {ve})"
                new_ai_response_text = new_ai_response_text_raw
            except Exception as resp_err:
                 logger.error(f"Erro ao processar resposta da IA pós-edição (Chat {chat.id}): {resp_err}", exc_info=True)
                 new_ai_response_text_raw = "(Erro interno ao obter nova resposta da IA)"
                 new_ai_response_text = new_ai_response_text_raw


            # Salva a nova resposta da IA
            new_ai_message = ChatMessage.objects.create(chat=chat, sender='ai', text=new_ai_response_text)
            logger.info(f"Nova resposta da IA (msg {new_ai_message.id}) gerada após edição no chat {chat.id}.")

            # LOGAR USO DA API (EDIÇÃO)
            if gemini_resp_edit and hasattr(gemini_resp_edit, 'usage_metadata'):
                log_api_usage(
                    user=user, model_name=model_name, ai_message=new_ai_message,
                    usage_metadata=gemini_resp_edit.usage_metadata, image_count=0 # Edição não envia imagens
                )
            elif gemini_resp_edit:
                 logger.warning(f"Resposta Gemini pós-edição (msg {new_ai_message.id}) não continha 'usage_metadata'. Custo não registrado.")

            # Atualiza o 'updated_at' do chat
            chat.updated_at = new_ai_message.created_at
            chat.save(update_fields=['updated_at'])

            # Retorna sucesso
            return JsonResponse({
                'status': 'edited_and_reprocessed',
                'message': 'Mensagem editada e IA reprocessada com sucesso.',
            })

        except Exception as ia_ex:
            # Erro na chamada da API durante reprocessamento
            logger.error(f"Falha ao reprocessar IA após edição da msg {message_id} no chat {chat_id}: {ia_ex}", exc_info=True)
            # A edição do texto do usuário FOI salva. Atualiza updated_at.
            try:
                chat.updated_at = timezone.now()
                chat.save(update_fields=['updated_at'])
            except Exception as save_err:
                 logger.error(f"Erro adicional ao salvar updated_at após falha no reprocessamento: {save_err}")

            # Retorna status 207 (Multi-Status): edição OK, reprocessamento falhou
            return JsonResponse({
                   'status': 'edited_only',
                   'warning': f'Mensagem editada com sucesso, mas falha ao gerar nova resposta da IA: {type(ia_ex).__name__}'
            }, status=207)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido no corpo da requisição.'}, status=400)
    except ChatMessage.DoesNotExist:
        return JsonResponse({'error': 'Mensagem a editar não encontrada ou inválida.'}, status=404)
    except Exception as e:
        logger.exception(f"Erro inesperado ao editar mensagem {message_id} no chat {chat_id}: {e}")
        return JsonResponse({'error': 'Erro interno ao processar a edição da mensagem.'}, status=500)


# ==============================================================================
# == VIEW DE UPLOAD SEPARADA (LEGADO/REDUNDANTE) ==
# ==============================================================================
@login_required
@csrf_exempt
@require_http_methods(["POST"])
def upload_file_to_chat_view(request, chat_id):
    """(LEGADO?) Recebe arquivos e salva como anexo no chat, SEM interação com IA."""
    user = request.user
    logger.warning(f"Chamada à view LEGADA 'upload_file_to_chat_view' para chat {chat_id} por '{user.username}'.")

    try:
        chat = get_object_or_404(Chat, id=chat_id, user=user)
    except Chat.DoesNotExist:
        return JsonResponse({'error': 'Chat não encontrado ou acesso não permitido.'}, status=404)
    except Exception as e:
        logger.exception(f"Erro ao buscar chat {chat_id} para upload LEGADO: {e}")
        return JsonResponse({'error': 'Erro interno ao buscar dados do chat.'}, status=500)

    if not request.FILES:
        return JsonResponse({'error': 'Nenhum arquivo enviado.'}, status=400)

    files = request.FILES.getlist('arquivo')
    if not files:
        return JsonResponse({'error': 'Nenhum arquivo encontrado no campo "arquivo".'}, status=400)

    logger.info(f"Recebidos {len(files)} arquivo(s) para upload LEGADO no chat {chat.id}.")
    saved_attachments_info = []
    errors = []
    last_upload_time = None

    for f in files:
        original_filename = f.name
        attachment = None
        try:
            logger.debug(f"Processando arquivo '{original_filename}' para upload LEGADO (Chat {chat.id})")
            # Validação de Tamanho
            if f.size > MAX_UPLOAD_SIZE_BYTES:
                raise ValueError(f"Arquivo excede o limite de {MAX_UPLOAD_SIZE_MB}MB.")

            # Salva o anexo SEM mensagem associada
            attachment = ChatAttachment(chat=chat, file=f, message=None)
            attachment.save()
            last_upload_time = attachment.uploaded_at

            saved_filename = attachment.file.name
            display_filename = attachment.get_filename()
            logger.info(f"Anexo '{original_filename}' salvo como '{saved_filename}' (ID: {attachment.id}) no upload LEGADO (Chat {chat.id}).")
            saved_attachments_info.append({
                'id': attachment.id, 'filename': display_filename, 'file_url': attachment.file.url,
                'uploaded_at': attachment.uploaded_at.isoformat()
            })

        except ValueError as ve:
            errors.append({'filename': original_filename, 'error': str(ve)})
        except Exception as upload_err:
            logger.error(f"Falha inesperada no upload LEGADO do arquivo '{original_filename}': {upload_err}", exc_info=True)
            errors.append({'filename': original_filename, 'error': 'Erro interno durante o upload.'})
            if attachment and attachment.pk:
                try: attachment.delete()
                except Exception: pass

    # Define status final
    final_status_code = 200 if not errors else (207 if saved_attachments_info else 400)
    overall_status = 'failure'
    if saved_attachments_info and errors: overall_status = 'partial_success'
    elif saved_attachments_info: overall_status = 'success'
    response_message = f'{len(saved_attachments_info)} arquivo(s) salvos, {len(errors)} falha(s) (Upload Legado).'

    # Atualiza 'updated_at' do chat se algum arquivo foi salvo
    if last_upload_time:
        try:
            chat.updated_at = last_upload_time
            chat.save(update_fields=['updated_at'])
        except Exception as final_save_err:
            logger.error(f"Erro ao atualizar 'updated_at' final para chat {chat.id} após upload LEGADO: {final_save_err}")

    return JsonResponse({
        'status': overall_status, 'message': response_message,
        'saved_attachments': saved_attachments_info, 'upload_errors': errors
    }, status=final_status_code)


# ==============================================================================
# VIEW DE MONITORAMENTO DE CUSTOS
# ==============================================================================
@login_required
def api_cost_monitor_view(request):
    """Exibe um resumo dos custos de uso da API com filtros."""
    can_view_all = request.user.has_perm('ia.view_all_api_costs')

    form = None
    summary_data = {}
    user_to_filter = request.user if not can_view_all else None
    selected_start_date = None
    selected_end_date = None
    selected_model_name = None

    if ApiUsageFilterForm:
        form_initial = {}
        if user_to_filter:
            form_initial['user'] = user_to_filter

        form = ApiUsageFilterForm(request.GET or None, initial=form_initial)

        # Popula Choices do Modelo dinamicamente
        try:
            distinct_models = ApiUsageLog.objects.values_list('model_name', flat=True)\
                                                 .distinct().order_by('model_name')
            model_choices = [('', '-- Todos os Modelos --')] + [(name, name) for name in distinct_models if name]
            form.fields['model_name'].choices = model_choices
        except Exception as e:
            logger.error(f"Erro ao buscar modelos distintos para filtro: {e}")
            form.fields['model_name'].choices = [('', '-- Todos os Modelos --')]

        # Ajusta campo de usuário baseado na permissão
        if not can_view_all:
            if 'user' in form.fields:
                form.fields['user'].widget = forms.HiddenInput()
                form.fields['user'].required = False
                form.fields['user'].queryset = User.objects.filter(pk=request.user.pk)
                form.fields['user'].disabled = True
        # else: Campo fica visível e editável

        if form.is_valid():
            selected_start_date = form.cleaned_data.get('start_date')
            selected_end_date = form.cleaned_data.get('end_date')
            selected_model_name = form.cleaned_data.get('model_name')

            if can_view_all:
                user_to_filter = form.cleaned_data.get('user')
            # else: user_to_filter já está request.user

    else: # Fallback se ApiUsageFilterForm não existir
        form = lambda: None
        form.is_valid = lambda: False
        form.cleaned_data = {}
        form.as_p = lambda: "<p>Formulário de filtro indisponível.</p>"


    # Obtém Dados Sumarizados
    try:
        summary_data = ApiUsageLog.get_cost_summary(
            user=user_to_filter,
            start_date=selected_start_date,
            end_date=selected_end_date,
            model_name=selected_model_name
        )
    except Exception as summary_error:
        logger.error(f"Erro ao calcular resumo de custos: {summary_error}", exc_info=True)


    context = {
        'summary': summary_data,
        'form': form,
        'selected_start_date': selected_start_date,
        'selected_end_date': selected_end_date,
        'selected_user_filter': user_to_filter,
        'selected_model_filter': selected_model_name,
        'can_view_all': can_view_all,
    }
    return render(request, 'ia/api_cost_monitor.html', context)