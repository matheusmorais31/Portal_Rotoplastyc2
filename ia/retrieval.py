import logging
import os
import re
from typing import List, Dict, Any, Sequence, Optional

import numpy as np
from django.conf import settings
from django.db.models import QuerySet

from documentos.models import Documento

try:
    import google.generativeai as genai
except ImportError:  # lib pode não estar instalada no ambiente de desenvolvimento
    genai = None  # type: ignore

# ---------------------------------------------------------------------------
# Configurações globais
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Limite de caracteres que mandamos à IA (mesmo valor usado em extract_text_from_file)
MAX_EXTRACTION_CHARS: int = getattr(settings, "IA_MAX_FILE_EXTRACTION_CHARS", 10_000)

# Limite padrão de documentos a retornar em consultas genéricas
DEFAULT_TOP_K: int = getattr(settings, "IA_DEFAULT_TOP_K", 15)

# Parâmetros de chunking se não detectarmos código de documento
CHUNK_SIZE: int = 1_200  # caracteres
CHUNK_STRIDE: int = 100  # sobreposição

# Expressão que detecta códigos de documento (ex.: DS06, MPCL01, DS135)
DOC_CODE_RE = re.compile(r"\b([a-z]{2}[a-z]*\d{2,3})\b", re.IGNORECASE)

# Stop‑words muito comuns que tendem a poluir os scores de similaridade simples
STOP_WORDS = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "as", "os", "para", "por", "em", "no", "na"
}

# ---------------------------------------------------------------------------
# Funções utilitárias de embedding (opcional, usadas se embed_text() for chamado)
# ---------------------------------------------------------------------------

def _configure_genai_once() -> None:
    """Configura a lib google‑generativeai apenas uma vez se a API key existir."""
    if genai is None:
        return
    if not genai._default_api_key:  # type: ignore[attr-defined]
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if api_key:
            genai.configure(api_key=api_key)
        else:
            logger.debug("GEMINI_API_KEY não configurada; embed_text ficará inativo.")


Configure_once_flag = False

def embed_text(text: str, *, model_name: str = "models/embedding-001") -> Optional[np.ndarray]:
    """Gera embedding do texto usando a API Gemini."""
    global Configure_once_flag
    if genai is None:
        logger.debug("google.generativeai não instalado – embed_text ignorado.")
        return None

    if not Configure_once_flag:
        _configure_genai_once()
        Configure_once_flag = True

    try:
        model = genai.embedder(model_name)  # type: ignore[attr-defined]
        response = model.embed(content=text)
        # Algumas versões retornam dict, outras objeto com .embedding
        emb = np.array(response.embedding if hasattr(response, "embedding") else response["embedding"])  # type: ignore[index]
        return emb.astype(np.float32)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("embed_text: erro ao gerar embedding: %s", exc, exc_info=True)
        return None

# ---------------------------------------------------------------------------
# Chunking auxiliar (usado em queries genéricas)
# ---------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE, stride: int = CHUNK_STRIDE) -> List[str]:
    if len(text) <= size:
        return [text]
    chunks = [
        text[i : i + size]  # noqa: E203  (black slice)
        for i in range(0, len(text), size - stride)
    ]
    return chunks

# ---------------------------------------------------------------------------
# Algoritmo de busca / recuperação
# ---------------------------------------------------------------------------

def _score_simple(text: str, terms: Sequence[str]) -> int:
    """Pontuação simples: frequência ponderada dos termos (tokens) no texto."""
    s = 0
    lower = text.lower()
    for t in terms:
        weight = 5 if DOC_CODE_RE.fullmatch(t) else 1
        s += lower.count(t) * weight
    return s


def _query_tokens(query: str) -> List[str]:
    return [t.lower() for t in re.findall(r"\w+", query) if t.lower() not in STOP_WORDS]


def find_relevant_document_chunks(
    user, query: str, *, top_k: int = DEFAULT_TOP_K
) -> List[Dict[str, Any]]:
    """Devolve lista de dicionários: {doc, snippet, score}.

    * **Opção B implementada**: se o `query` contiver explicitamente um código de documento
      (DS06, DS135, MPCL01, etc.), devolvemos o(s) documento(s) inteiro(s) (truncados em
      `MAX_EXTRACTION_CHARS`) e pulamos o algoritmo de chunking.
    """

    docs_qs: QuerySet[Documento] = Documento.objects.filter(
        status="aprovado", is_active=True
    ).select_related("categoria")

    # ------------------------------------------------------------------
    # Detecta código de documento (DS06, DS135, MPCL02 …)
    # ------------------------------------------------------------------
    code_match = DOC_CODE_RE.search(query)
    if code_match:
        code = code_match.group(1).lower()
        matched_docs = docs_qs.filter(nome__istartswith=code)
        if matched_docs.exists():
            logger.debug("find_relevant: match exato de código '%s' – devolvendo texto completo", code)
            results = []
            for d in matched_docs:
                txt = (d.text_content or "")[:MAX_EXTRACTION_CHARS]
                results.append({
                    "doc": d,
                    "snippet": txt,
                    "score": 999  # prioridade máxima
                })
            return results[:top_k]

    # ------------------------------------------------------------------
    # Caminho normal (query genérica) – scoring simples + chunking
    # ------------------------------------------------------------------

    terms = _query_tokens(query)
    if not terms:
        return []

    results: List[Dict[str, Any]] = []

    for d in docs_qs:
        text = d.text_content or ""
        if not text:
            continue  # nada para ranquear

        # se o texto for pequeno já usa ele inteiro
        if len(text) <= CHUNK_SIZE:
            snippet = text
            score = _score_simple(text, terms)
            if score:
                results.append({"doc": d, "snippet": snippet, "score": score})
            continue

        # senão: divide em chunks e pega o melhor
        best_chunk_score = 0
        best_chunk = ""
        for chunk in chunk_text(text):
            c_score = _score_simple(chunk, terms)
            if c_score > best_chunk_score:
                best_chunk_score = c_score
                best_chunk = chunk
        if best_chunk_score:
            results.append({"doc": d, "snippet": best_chunk, "score": best_chunk_score})

    # ordena, remove duplicados pelo código base e devolve top_k
    ordered = sorted(results, key=lambda x: x["score"], reverse=True)

    unique: Dict[str, Dict[str, Any]] = {}
    for r in ordered:
        code = r["doc"].nome.split()[0].lower()
        if code not in unique:
            unique[code] = r
    return list(unique.values())[:top_k]

# ---------------------------------------------------------------------------
# Vector search placeholder (não usado se você não tiver pgvector, etc.)
# ---------------------------------------------------------------------------

def vector_search(query_embedding: np.ndarray, k: int = 5):
    """Exemplo de stub que você pode ligar a pgvector ou FAISS."""
    logger.debug("vector_search chamado, mas não implementado.")
    return []
