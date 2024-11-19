# notificacoes/views.py

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Notificacao
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@login_required
def listar_notificacoes(request):
    notificacoes_nao_lidas = Notificacao.objects.filter(destinatario=request.user, lida=False).order_by('-data_criacao')
    return render(request, 'notificacoes/listar_notificacoes.html', {'notificacoes_nao_lidas': notificacoes_nao_lidas})

@login_required
@csrf_exempt
def marcar_notificacao_como_lida(request, notificacao_id):
    if request.method == 'POST':
        try:
            notificacao = Notificacao.objects.get(id=notificacao_id, destinatario=request.user)
            notificacao.lida = True
            notificacao.save()
            return JsonResponse({'status': 'success'})
        except Notificacao.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Notificação não encontrada.'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Método não permitido.'})

@login_required
@csrf_exempt
def limpar_todas_notificacoes(request):
    if request.method == 'POST':
        try:
            notificacoes = Notificacao.objects.filter(destinatario=request.user, lida=False)
            notificacoes.update(lida=True)
            return JsonResponse({'status': 'success', 'total_limpos': notificacoes.count()})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    else:
        return JsonResponse({'status': 'error', 'message': 'Método não permitido.'})
