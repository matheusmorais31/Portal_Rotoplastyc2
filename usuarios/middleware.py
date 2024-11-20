import re
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

EXEMPT_URLS = [re.compile(reverse('usuarios:login_usuario').lstrip('/'))]
EXEMPT_URLS += [re.compile(settings.MEDIA_URL.lstrip('/'))]
EXEMPT_URLS += [re.compile('admin/')]  # Exemplo para excluir a área administrativa

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        assert hasattr(request, 'user')
        path = request.path_info.lstrip('/')

        if not request.user.is_authenticated:
            if not any(url.match(path) for url in EXEMPT_URLS):
                return redirect(settings.LOGIN_URL)
        return self.get_response(request)
