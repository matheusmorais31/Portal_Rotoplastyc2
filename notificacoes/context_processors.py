# notificacoes/context_processors.py

from .models import Notificacao

def notificacoes_nao_lidas(request):
    if request.user.is_authenticated:
        notificacoes = Notificacao.objects.filter(destinatario=request.user, lida=False).order_by('-data_criacao')
        return {'notificacoes_nao_lidas': notificacoes}
    else:
        return {}
