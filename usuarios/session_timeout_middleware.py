# usuarios/session_timeout_middleware.py

from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from django.contrib.auth import logout
from datetime import datetime
import pytz

class SessionIdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Tenta obter a última atividade da sessão
            last_activity_str = request.session.get('last_activity')
            now = timezone.now()

            if last_activity_str:
                # Converte a string ISO de volta para datetime
                # Caso o datetime tenha sido salvo com fuso horário:
                last_activity = datetime.fromisoformat(last_activity_str)

                # Calcula a diferença entre agora e a última atividade
                elapsed = (now - last_activity).total_seconds()

                # Verifica se a inatividade excede o tempo limite
                if elapsed > getattr(settings, 'SESSION_IDLE_TIMEOUT', 1800):
                    # Tempo expirado por inatividade, faz logout e redireciona
                    logout(request)
                    return redirect('usuarios:login_usuario')

            # Atualiza o timestamp da última atividade em formato ISO antes de salvar
            request.session['last_activity'] = now.isoformat()

        response = self.get_response(request)
        return response
