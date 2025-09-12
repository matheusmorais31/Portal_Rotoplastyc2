from django.shortcuts import render
import requests
import time
import logging
from django.contrib.auth.decorators import login_required
from django.db import models  # mantido caso use noutras views
from datetime import datetime, timedelta
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.conf import settings

from formularios.models import Formulario

logger = logging.getLogger(__name__)

# ========================== CACHE DO CLIMA ==========================
previsao_cache = None
ultima_atualizacao = 0


# ========================== HELPERS POPUP ==========================

def _safe_local_date(dt: datetime | None):
    """
    Retorna a data local de forma tolerante a datetime naive/aware
    e a USE_TZ True/False.
    """
    if dt is None:
        dt = timezone.now()
    try:
        return timezone.localtime(dt).date()
    except Exception:
        return dt.date()


def _form_esta_aberto(form: Formulario, now: datetime) -> bool:
    """Checa janela de disponibilidade e se está aceitando respostas."""
    if hasattr(form, "aceita_respostas") and not form.aceita_respostas:
        return False
    if form.abre_em and form.abre_em > now:
        return False
    if form.fecha_em and form.fecha_em < now:
        return False
    return True


def _eligivel_por_alvo(request, form: Formulario, now: datetime) -> bool:
    """
    Decide se o visitante deve ver o popup conforme alvo_resposta:

      - ALL (100%): todos (logados ou anônimos).
      - HALF (50%): metade vê em cada *ciclo*. O ciclo é calculado por
        'Repetir a cada' se > 0; caso contrário, cai no ciclo diário.
      - MAN (manual): somente usuários selecionados (exige autenticado).

    Para HALF usamos uma semente estável:
      user.pk (se logado) OU session_key (anônimo) OU IP,
    combinada com o id do formulário. Alterna grupos por ciclo.
    """
    alvo = getattr(form, "alvo_resposta", Formulario.AlvoChoices.ALL)

    # 100% – todos
    if alvo == Formulario.AlvoChoices.ALL:
        return True

    # Manual – apenas os escolhidos
    if alvo == Formulario.AlvoChoices.MAN:
        return (
            request.user.is_authenticated
            and form.alvo_usuarios.filter(pk=request.user.pk).exists()
        )

    # 50% – alterna por ciclo baseado no repetir_cada
    if alvo == Formulario.AlvoChoices.HALF:
        interval = getattr(form, "repetir_cada", timedelta(0)) or timedelta(0)
        start = form.abre_em or form.criado_em or now

        if interval.total_seconds() > 0:
            # ciclo = inteiro desde o início, com base no intervalo configurado
            cycle = int((now - start) / interval)
        else:
            # sem intervalo definido: alterna diariamente
            cycle = _safe_local_date(now).toordinal()

        # Semente estável por visitante
        seed = (
            str(getattr(request.user, "pk", ""))  # id se logado
            or (request.session.session_key or request.META.get("REMOTE_ADDR", "0"))
        )
        import hashlib
        digest = int(hashlib.sha256(f"{seed}:{form.pk}".encode()).hexdigest(), 16)
        group = digest % 2  # 0 ou 1

        return group == (cycle % 2)

    # fallback
    return True


# ========================== ÍCONE / CLIMA ==========================
def selecionar_icone(condicao):
    condicao_map = {
        'sol com algumas nuvens': '2',
        'sol com muitas nuvens': '2r',
        'sol': '1',
        'noite sem nuvens': '1n',
        'noite com algumas nuvens': '2n',
        'noite com muitas nuvens': '2rn',
        'nublado': '3',
        'sol e chuva': '4',
        'sol com muitas nuvens e chuva': '4r',
        'noite chuvosa': '4n',
        'noite nublada e chuvosa': '4rn',
        'sol entre nuvens e pancadas de chuva, com trovoadas': '4t',
        'pancadas de chuva durante a noite': '4tn',
        'chuvoso': '5',
        'chuva e trovoadas': '6',
        'geada': '7',
        'neve': '8',
        'nevoeiro': '9',
        'pancadas de chuva': '4',
        'muitas nuvens': '3',
        'céu limpo': '1',
        'algumas nuvens': 'nublado',
    }

    condicao_normalizada = (condicao or "").lower()
    for chave, icone in condicao_map.items():
        if chave in condicao_normalizada:
            return icone
    return 'default'


def obter_clima_atual(cidade_id, api_key):
    url_atual = f"https://apiadvisor.climatempo.com.br/api/v1/weather/locale/{cidade_id}/current?token={api_key}"
    try:
        resposta = requests.get(url_atual, verify=False)
        resposta.raise_for_status()
        dados = resposta.json()
        condicao_clima = dados['data']['condition']
        clima_atual = {
            'temperatura_atual': dados['data']['temperature'],
            'sensacao': dados['data']['sensation'],
            'humidade': dados['data']['humidity'],
            'condicao': condicao_clima,
            'icone': selecionar_icone(condicao_clima),
            'data': dados['data']['date']
        }
        logger.debug(f"Clima atual obtido: {clima_atual}")
        return clima_atual
    except Exception as e:
        logger.error(f"Erro ao obter clima atual: {e}")
        return None


def obter_previsao_15_dias(cidade_id, api_key, intervalo_cache=3600):
    global previsao_cache, ultima_atualizacao

    if time.time() - ultima_atualizacao > intervalo_cache or previsao_cache is None:
        url_previsao = f"https://apiadvisor.climatempo.com.br/api/v1/forecast/locale/{cidade_id}/days/15?token={api_key}"
        try:
            resposta = requests.get(url_previsao, verify=False)
            resposta.raise_for_status()
            dados = resposta.json()
            previsao = []
            for dia in dados.get('data', []):
                condicao_clima = dia['text_icon']['text']['phrase']['reduced']
                previsao.append({
                    'data': dia['date'],
                    'data_br': dia['date_br'],
                    'temperatura_min': dia['temperature']['min'],
                    'temperatura_max': dia['temperature']['max'],
                    'condicao': condicao_clima,
                    'condicao_icone': selecionar_icone(condicao_clima),
                    'probabilidade_chuva': dia['rain']['probability'],
                })
            previsao_cache = previsao
            ultima_atualizacao = time.time()
            logger.debug("Previsão atualizada e armazenada em cache.")
        except Exception as e:
            logger.error(f"Erro ao obter previsão: {e}")
            return None

    return previsao_cache


# ========================== HOME ==========================
@login_required
def home(request):
    # --------- Parâmetro opcional para testes: ?force_popup=1 ---------
    force_popup = request.GET.get("force_popup") == "1"

    agora = timezone.now()
    form_popup = None

    candidatos = (
        Formulario.objects
        .filter(aparece_home=True, aceita_respostas=True)
        .order_by('-criado_em')
    )

    for f in candidatos:
        if not _form_esta_aberto(f, agora):
            continue

        # se o form não é público e o visitante está anônimo, não mostra
        if not getattr(f, "publico", True) and not request.user.is_authenticated:
            continue

        # alvo (100% / 50% / manual), a menos que esteja forçando para teste
        if not force_popup and not _eligivel_por_alvo(request, f, agora):
            continue

        # ===== respeita "Repetir a cada" em relação à ÚLTIMA RESPOSTA do usuário =====
        intervalo = getattr(f, "repetir_cada", None)  # << mantém None (difere de 0)
        last_answer_dt = None

        # (home é login_required, então basta olhar respostas do usuário logado)
        last = (
            f.respostas.filter(enviado_por=request.user)
            .only("enviado_em").order_by("-enviado_em").first()
        )
        if last:
            last_answer_dt = last.enviado_em

        if not force_popup and last_answer_dt:
            # • respondeu e repetir_cada é None OU 0  => NUNCA repetir
            if not intervalo or intervalo.total_seconds() == 0:
                continue
            # • respondeu e repetir_cada > 0 => só reabre após o intervalo
            if (agora - last_answer_dt) < intervalo:
                continue

        # ===== também respeita intervalo entre exibições (não abrir repetidamente) =====
        # só faz sentido quando há um intervalo > 0
        if not force_popup and intervalo and intervalo.total_seconds() > 0:
            last_show_iso = request.session.get(f"form_last_show_{f.pk}")
            if last_show_iso:
                try:
                    last_show_dt = datetime.fromisoformat(last_show_iso)
                except Exception:
                    last_show_dt = None
                else:
                    if (agora - last_show_dt) < intervalo:
                        continue

        # selecionado!
        form_popup = f
        # marca exibição agora (controle de “repetir a cada” por exibição)
        try:
            request.session[f"form_last_show_{f.pk}"] = agora.isoformat()
            request.session.modified = True
        except Exception:
            pass
        break

    # --------- Clima (mantido) ---------
    cidade_id = 5585  # Carazinho, RS
    api_key = '5f713c18b31aee4d7a93df6a3220cfb8'

    clima_atual = obter_clima_atual(cidade_id, api_key)
    previsao = obter_previsao_15_dias(cidade_id, api_key)

    dia_atual = int(request.GET.get('dia', 0) or 0)
    if dia_atual < 0:
        dia_atual = 0

    erro = ''
    if clima_atual and previsao:
        if dia_atual < len(previsao):
            previsao_atual = previsao[dia_atual]
        else:
            previsao_atual = previsao[0]
            dia_atual = 0
    else:
        previsao_atual = None
        erro = 'Erro ao obter dados do tempo.'

    context = {
        'clima_atual': clima_atual,
        'previsao': previsao_atual,
        'dia_atual': dia_atual,
        'erro': erro,
        'form_popup': form_popup,
    }

    logger.debug(
        "HOME ctx: popup=%s, dia=%s, erro=%s, force=%s",
        getattr(form_popup, "pk", None), dia_atual, bool(erro), force_popup
    )
    return render(request, 'home.html', context)

# ========================== PÁGINAS DIVERSAS ==========================
def tecnicon(request):
    return render(request, 'tecnicon.html')

def monitores(request):
    return render(request, 'monitores.html')

def allcance(request):
    return render(request, 'allcance.html')

def glpi(request):
    return render(request, 'glpi.html')

def gestao(request):
    return render(request, 'gestao.html')

def mural(request):
    return render(request, 'mural.html')

def manuais(request):
    return render(request, 'manuais.html')

def andon(request):
    return render(request, 'andon.html')

def andonfilial(request):
    return render(request, 'andonfilial.html')

def assinatura(request):
    return render(request, 'assinatura.html')

def descricao(request):
    return render(request, 'descricao.html')

def indicadores(request):
    return render(request, 'indicadores.html')

def beneficios(request):
    return render(request, 'beneficios.html')

def odonto(request):
    return render(request, 'odonto.html')

def regulamentos(request):
    return render(request, 'regulamentos.html')


