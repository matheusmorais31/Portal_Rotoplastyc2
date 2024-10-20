from .models import Notificacao

def notificacoes_nao_lidas(request):
    if request.user.is_authenticated:
        notificacoes = Notificacao.objects.filter(destinatario=request.user, lida=False)
        return {'notificacoes_nao_lidas': notificacoes}
    return {'notificacoes_nao_lidas': []}
