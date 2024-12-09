from django import template
from django.utils.html import mark_safe
import re

register = template.Library()

@register.simple_tag
def render_bi_embed(embed_code):
    # Expressão regular para extrair o URL do src do iframe
    match = re.search(r'src="([^"]+)"', embed_code)
    if match:
        src_url = match.group(1)
        # Adicionar os parâmetros desejados
        if '?' in src_url:
            src_url += '&'
        else:
            src_url += '?'
        # Parâmetros fixos para remover a opção de compartilhar
        src_url += 'toolbar=false&filterPaneEnabled=false'
        # Reconstruir o iframe com o src modificado
        iframe_code = re.sub(r'src="[^"]+"', f'src="{src_url}"', embed_code)
        return mark_safe(iframe_code)
    else:
        # Se não encontrar, retornar o código original
        return mark_safe(embed_code)
