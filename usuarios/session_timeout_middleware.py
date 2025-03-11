# usuarios/session_timeout_middleware.py

from django.conf import settings
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.utils import timezone
from datetime import datetime

class SessionIdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            last_activity_str = request.session.get('last_activity')
            # Obtém o datetime atual; quando USE_TZ=False, timezone.now() retorna um datetime naive
            now = timezone.now()

            if last_activity_str:
                try:
                    last_activity = datetime.fromisoformat(last_activity_str)
                except Exception:
                    # Se der erro na conversão, assume que não há atividade registrada
                    last_activity = None

                if last_activity:
                    # Se last_activity for aware (tem tzinfo), converte para naive usando o fuso local
                    if last_activity.tzinfo is not None:
                        last_activity = last_activity.astimezone(timezone.get_current_timezone()).replace(tzinfo=None)
                    # Calcula o tempo decorrido (em segundos)
                    elapsed = (now - last_activity).total_seconds()
                    if elapsed > getattr(settings, 'SESSION_IDLE_TIMEOUT', 1800):
                        logout(request)
                        return redirect('usuarios:login_usuario')

            # Atualiza o timestamp da última atividade na sessão (salvo como string ISO sem timezone)
            request.session['last_activity'] = now.replace(tzinfo=None).isoformat()

        response = self.get_response(request)
        return response
