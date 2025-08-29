# formularios/templatetags/form_extras.py
from django import template

register = template.Library()

# -------------------------
# Utilidades genéricas
# -------------------------
@register.filter
def get_item(dictionary, key):
    """{{ dict|get_item:key }}"""
    if hasattr(dictionary, "get"):
        return dictionary.get(str(key))
    return None

# Para texto único (texto_curto, paragrafo, lista, escala, data, hora, multipla)
@register.filter
def primeiro_texto(valores, campo_id):
    """
    Retorna o primeiro valor_texto do campo informado ou ''.
    Usa-se assim: {% with txt=valores_resposta|primeiro_texto:campo.id %}{{ txt }}{% endwith %}
    """
    if not valores:
        return ""
    for v in valores:
        try:
            if getattr(v, "campo_id", None) == campo_id and getattr(v, "valor_texto", None):
                return v.valor_texto
        except Exception:
            pass
    return ""

# Para checkbox — mantemos string agregada para o template testar "in"
@register.filter
def selecoes_checkbox(valores, campo_id):
    """
    Retorna a string armazenada (ex.: 'A;B;C' ou semelhante) do campo checkbox,
    para o template fazer: {% if val_op in sel %}checked{% endif %}
    """
    if not valores:
        return ""
    for v in valores:
        try:
            if getattr(v, "campo_id", None) == campo_id and getattr(v, "valor_texto", None):
                return v.valor_texto
        except Exception:
            pass
    return ""

# Para arquivos — lista de valores com arquivo
@register.filter
def arquivos_do_campo(valores, campo_id):
    """
    Retorna lista [v, v, ...] de valores que possuem valor_arquivo para o campo.
    """
    out = []
    if not valores:
        return out
    for v in valores:
        try:
            if getattr(v, "campo_id", None) == campo_id and getattr(v, "valor_arquivo", None):
                out.append(v)
        except Exception:
            pass
    return out

# -------------------------
# Aceites por categoria (se você já usava)
# -------------------------
CATEGORIAS_ARQUIVO = {
    "Documento":    ['doc', 'docx', 'odt', 'txt', 'rtf'],
    "Apresentação": ['ppt', 'pptx', 'odp'],
    "Planilha":     ['xls', 'xlsx', 'ods', 'csv'],
    "Desenho":      ['dwg', 'dxf'],
    "PDF":          ['pdf'],
    "Imagem":       ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'],
    "Vídeo":        ['mp4', 'mov', 'avi', 'mkv', 'wmv'],
    "Áudio":        ['mp3', 'wav', 'ogg', 'aac'],
}

@register.filter
def get_extensions_for_categories(categories):
    """
    Recebe lista de categorias e devolve ".pdf,.jpg,..." para usar em accept=.
    """
    if not categories:
        return ""
    exts = []
    for nome in categories:
        exts.extend(CATEGORIAS_ARQUIVO.get(nome, []))
    return ",".join(f".{e}" for e in set(exts))
