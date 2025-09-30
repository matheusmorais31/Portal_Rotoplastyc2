from __future__ import annotations

from django.shortcuts import render
import unicodedata, re
import requests
import logging
import time
import random
from django.contrib.auth.decorators import login_required
from django.db import models  # mantido caso use noutras views
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache

from formularios.models import Formulario

logger = logging.getLogger(__name__)

# ========================== TTLs configuráveis ==========================
# Pode sobrescrever no settings.py:
# CLIMA_TTL_ATUAL (padrão 300s), CLIMA_TTL_PREVISAO (10800s), CLIMA_TTL_LKG (7 dias)
FRESH_TTL_ATUAL = getattr(settings, 'CLIMA_TTL_ATUAL', 300)              # 5 min
FRESH_TTL_PREVISAO = getattr(settings, 'CLIMA_TTL_PREVISAO', 10800)      # 3 h
LKG_TTL_SECONDS = getattr(settings, 'CLIMA_TTL_LKG', 7 * 24 * 3600)      # 7 dias

# ========================== Rate limit helpers (circuit breaker) ==========================
def _snooze_key(ns: str) -> str:
    return f"ratelimit:{ns}:until"

def _snooze_until(ns: str, seconds: int):
    """Evita novas chamadas ao namespace por 'seconds'."""
    seconds = max(60, int(seconds))  # pelo menos 1 min
    until_ts = time.time() + seconds
    cache.set(_snooze_key(ns), until_ts, seconds)

def _is_snoozed(ns: str) -> bool:
    until_ts = cache.get(_snooze_key(ns))
    return bool(until_ts and time.time() < float(until_ts))

def _ttl_with_jitter(ttl: int, jitter_pct: float = 0.15) -> int:
    """Evita carimbada simultânea de expiração entre workers."""
    jitter = random.uniform(-jitter_pct, jitter_pct)
    return max(30, int(ttl * (1 + jitter)))

def _acquire_lock(lock_key: str, ttl: int = 30) -> bool:
    """Lock simples via cache.add. Se já existir, alguém está buscando."""
    return cache.add(lock_key, "1", timeout=ttl)

def _release_lock(lock_key: str):
    cache.delete(lock_key)

def _lkg_key(cache_key: str) -> str:
    return cache_key + ":lkg"

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
            cycle = int((now - start) / interval)
        else:
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
def _norm(txt: str) -> str:
    """lower + remove acentos/pontuação + colapsa espaços."""
    if not txt:
        return ""
    s = unicodedata.normalize("NFKD", str(txt))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def selecionar_icone(condicao: str) -> str:
    """
    Mapeia descrição textual → nome do ícone.
    Ordem: mais específico → mais genérico (evita 'chuva' engolir 'pancadas de chuva').
    """
    t = _norm(condicao)

    rules = (
        # noite + chuva primeiro
        ("noite nublada e chuvosa", "4rn"),
        ("noite chuvosa",            "4n"),

        # chuva e variações
        ("pancadas de chuva",        "4"),
        ("chuva e trovoadas",        "6"),
        ("trovoada",                 "6"),
        ("temporal",                 "6"),
        ("tempestade",               "6"),
        ("chuvisco",                 "4"),
        ("garoa",                    "4"),
        ("chuvoso",                  "5"),
        ("chuva",                    "5"),

        # sol + nuvens
        ("sol com muitas nuvens e chuva", "4r"),
        ("sol e chuva",                    "4"),
        ("sol com muitas nuvens",          "2r"),
        ("sol com algumas nuvens",         "2"),

        # noite + nuvens
        ("noite com muitas nuvens",  "2rn"),
        ("noite com algumas nuvens", "2n"),
        ("noite sem nuvens",         "1n"),

        # nuvens genéricas / céu limpo
        ("muitas nuvens",            "3"),
        ("algumas nuvens",           "2"),
        ("nublado",                  "3"),
        ("ceu limpo",                "1"),
        ("sol",                      "1"),

        # fenômenos
        ("nevoeiro",                 "9"),
        ("geada",                    "7"),
        ("neve",                     "8"),
    )

    for key, icon in rules:
        if key in t:
            return icon

    # fallback simpático: se a string ainda conter “chuva”, use 5; senão, default
    return "5" if "chuva" in t else "default"


# ========================== HTTP helper para Climatempo ==========================
def _fetch_json(url: str, timeout: int = 6):
    """
    Retorna (json|None, retry_after_seconds|None).
    Se 429, devolve (None, retry_after).
    Em outros erros, (None, None).
    """
    try:
        r = requests.get(url, timeout=timeout)  # verificação TLS habilitada (padrão)
        if r.status_code == 429:
            retry_after_hdr = r.headers.get("Retry-After")
            try:
                retry_after = int(retry_after_hdr) if retry_after_hdr else None
            except ValueError:
                retry_after = None
            logger.warning(
                "Climatempo 429 (rate limit). Retry-After=%s. URL=%s",
                retry_after_hdr, url
            )
            return None, retry_after
        r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        logger.error("Erro ao chamar Climatempo: %s", e)
        return None, None

# ========================== CLIMATEMPO WRAPPERS (com LKG + Circuit Breaker) ==========================
def obter_clima_atual(cidade_id: int, api_key: str, ttl_segundos: int = FRESH_TTL_ATUAL):
    """
    Retorna (data, stale_flag).
    Estratégia:
      - Respeita 'Retry-After' com snooze no cache (circuit breaker).
      - 1) tenta cache fresco
      - 2) se expirado, busca ao vivo
      - 3) se falhar, devolve LKG (último sucesso) se houver
    """
    ns = f"clima_atual:{cidade_id}"
    cache_key = ns
    lkg_key = _lkg_key(cache_key)

    # Se estamos "snoozed", não tenta rede — devolve fresco/LKG
    if _is_snoozed(ns):
        fresh = cache.get(cache_key)
        if fresh:
            return fresh, False
        lkg = cache.get(lkg_key)
        return (lkg, True) if lkg else (None, False)

    # 1) cache fresco
    fresh = cache.get(cache_key)
    if fresh:
        return fresh, False

    # lock anti-stampede
    lock_key = cache_key + ":lock"
    if not _acquire_lock(lock_key):
        # outro worker buscando — devolve o que tiver
        fresh = cache.get(cache_key)
        if fresh:
            return fresh, False
        lkg = cache.get(lkg_key)
        return (lkg, True) if lkg else (None, False)

    try:
        url = f"https://apiadvisor.climatempo.com.br/api/v1/weather/locale/{cidade_id}/current?token={api_key}"
        dados, retry_after = _fetch_json(url)
        if not dados:
            # Se veio Retry-After, ativa snooze
            if retry_after:
                _snooze_until(ns, retry_after)
            lkg = cache.get(lkg_key)
            return (lkg, True) if lkg else (None, False)

        condicao_clima = dados['data']['condition']
        clima_atual = {
            'temperatura_atual': dados['data']['temperature'],
            'sensacao': dados['data']['sensation'],
            'humidade': dados['data']['humidity'],
            'condicao': condicao_clima,
            'icone': selecionar_icone(condicao_clima),
            'data': dados['data']['date'],
        }
        cache.set(cache_key, clima_atual, _ttl_with_jitter(ttl_segundos))
        cache.set(lkg_key, clima_atual, LKG_TTL_SECONDS)
        return clima_atual, False
    finally:
        _release_lock(lock_key)

def obter_previsao_15_dias(cidade_id: int, api_key: str, ttl_segundos: int = FRESH_TTL_PREVISAO):
    """
    Retorna (lista_previsao, stale_flag).
    Respeita Retry-After via 'snooze' no cache.
    """
    ns = f"previsao_15:{cidade_id}"
    cache_key = ns
    lkg_key = _lkg_key(cache_key)

    if _is_snoozed(ns):
        fresh = cache.get(cache_key)
        if fresh:
            return fresh, False
        lkg = cache.get(lkg_key)
        return (lkg, True) if lkg else (None, False)

    fresh = cache.get(cache_key)
    if fresh:
        return fresh, False

    lock_key = cache_key + ":lock"
    if not _acquire_lock(lock_key):
        fresh = cache.get(cache_key)
        if fresh:
            return fresh, False
        lkg = cache.get(lkg_key)
        return (lkg, True) if lkg else (None, False)

    try:
        url = f"https://apiadvisor.climatempo.com.br/api/v1/forecast/locale/{cidade_id}/days/15?token={api_key}"
        dados, retry_after = _fetch_json(url)
        if not dados:
            if retry_after:
                _snooze_until(ns, retry_after)
            lkg = cache.get(lkg_key)
            return (lkg, True) if lkg else (None, False)

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

        cache.set(cache_key, previsao, _ttl_with_jitter(ttl_segundos))
        cache.set(lkg_key, previsao, LKG_TTL_SECONDS)
        return previsao, False
    finally:
        _release_lock(lock_key)

# ========================== OPEN-METEO HELPERS (fallback) ==========================
def _fetch_json_generic(url: str, timeout: int = 6, provider: str = "HTTP"):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.error("Erro ao chamar %s: %s (URL=%s)", provider, e, url)
        return None

# WMO → descrição simples em PT (usado pelo weather_code do Open-Meteo)
_WMO_DESC_PT = {
    0: "céu limpo",
    1: "algumas nuvens", 2: "algumas nuvens", 3: "nublado",
    45: "nevoeiro", 48: "nevoeiro",
    51: "chuvisco", 53: "chuvisco", 55: "chuvisco",
    56: "chuvisco congelante", 57: "chuvisco congelante",
    61: "chuva", 63: "chuva", 65: "chuva",
    66: "chuva congelante", 67: "chuva congelante",
    71: "neve", 73: "neve", 75: "neve",
    77: "grãos de neve",
    80: "pancadas de chuva", 81: "pancadas de chuva", 82: "pancadas de chuva",
    85: "pancadas de neve", 86: "pancadas de neve",
    95: "chuva e trovoadas",
    96: "trovoadas com granizo", 99: "trovoadas com granizo",
}

def _wmo_to_text(code: int, is_night: bool = False) -> str:
    base = _WMO_DESC_PT.get(int(code or 3), "nublado")
    if is_night:
        if code == 0:   return "noite sem nuvens"
        if code in (1, 2): return "noite com algumas nuvens"
    return base

def _iso_to_br(date_str: str) -> str:
    try:
        return datetime.fromisoformat(date_str).strftime("%d/%m/%Y")
    except Exception:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return date_str

def obter_clima_atual_openmeteo(lat: float, lon: float, tz: str, ttl_segundos: int = FRESH_TTL_ATUAL):
    """
    Retorna (data, stale_flag). Tenta payload 'current'; se ausente, usa o último passo 'hourly'.
    """
    ns = f"openmeteo_atual:{lat:.4f},{lon:.4f}"
    cache_key = ns
    lkg_key = _lkg_key(cache_key)

    fresh = cache.get(cache_key)
    if fresh:
        return fresh, False

    lock_key = cache_key + ":lock"
    if not _acquire_lock(lock_key):
        fresh = cache.get(cache_key)
        if fresh:
            return fresh, False
        lkg = cache.get(lkg_key)
        return (lkg, True) if lkg else (None, False)

    try:
        base = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&timezone={tz}"
        # Tenta 'current'
        url_cur = (base +
                   "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,is_day"
                   "&forecast_days=1")
        dados = _fetch_json_generic(url_cur, provider="Open-Meteo")

        now_payload = None
        if dados and isinstance(dados.get("current"), dict):
            now_payload = dados["current"]
        else:
            # Fallback: último horário
            url_hr = (base +
                      "&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,is_day"
                      "&past_hours=1&forecast_hours=0")
            dados_hr = _fetch_json_generic(url_hr, provider="Open-Meteo")
            if dados_hr and isinstance(dados_hr.get("hourly"), dict):
                h = dados_hr["hourly"]
                if h.get("time"):
                    idx = -1
                    now_payload = {
                        "time": h["time"][idx],
                        "temperature_2m": h.get("temperature_2m", [None])[idx],
                        "relative_humidity_2m": h.get("relative_humidity_2m", [None])[idx],
                        "apparent_temperature": h.get("apparent_temperature", [None])[idx],
                        "weather_code": h.get("weather_code", [None])[idx],
                        "is_day": h.get("is_day", [1])[idx],
                    }

        if not now_payload:
            lkg = cache.get(lkg_key)
            return (lkg, True) if lkg else (None, False)

        cond_txt = _wmo_to_text(now_payload.get("weather_code"), not bool(now_payload.get("is_day", 1)))
        clima_atual = {
            "temperatura_atual": now_payload.get("temperature_2m"),
            "sensacao": now_payload.get("apparent_temperature"),
            "humidade": now_payload.get("relative_humidity_2m"),
            "condicao": cond_txt,
            "icone": selecionar_icone(cond_txt),
            "data": now_payload.get("time"),
        }
        cache.set(cache_key, clima_atual, _ttl_with_jitter(ttl_segundos))
        cache.set(lkg_key, clima_atual, LKG_TTL_SECONDS)
        return clima_atual, False
    finally:
        _release_lock(lock_key)

def obter_previsao_openmeteo_15(lat: float, lon: float, tz: str, ttl_segundos: int = FRESH_TTL_PREVISAO):
    """
    Retorna (lista_previsao, stale_flag) usando 'daily':
      temperature_2m_min, temperature_2m_max, precipitation_probability_max, weather_code.
    """
    ns = f"openmeteo_15:{lat:.4f},{lon:.4f}"
    cache_key = ns
    lkg_key = _lkg_key(cache_key)

    fresh = cache.get(cache_key)
    if fresh:
        return fresh, False

    lock_key = cache_key + ":lock"
    if not _acquire_lock(lock_key):
        fresh = cache.get(cache_key)
        if fresh:
            return fresh, False
        lkg = cache.get(lkg_key)
        return (lkg, True) if lkg else (None, False)

    try:
        base = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&timezone={tz}"
        url = (base +
               "&daily=temperature_2m_min,temperature_2m_max,precipitation_probability_max,weather_code"
               "&forecast_days=15")
        dados = _fetch_json_generic(url, provider="Open-Meteo")
        if not dados or "daily" not in dados:
            lkg = cache.get(lkg_key)
            return (lkg, True) if lkg else (None, False)

        d = dados["daily"]
        times = d.get("time", [])
        tmin = d.get("temperature_2m_min", [])
        tmax = d.get("temperature_2m_max", [])
        pprob = d.get("precipitation_probability_max", [])
        wcode = d.get("weather_code", [])

        previsao = []
        for i in range(min(len(times), len(tmin), len(tmax), len(pprob), len(wcode))):
            cond_txt = _wmo_to_text(wcode[i], is_night=False)
            previsao.append({
                "data": times[i],
                "data_br": _iso_to_br(times[i]),
                "temperatura_min": tmin[i],
                "temperatura_max": tmax[i],
                "condicao": cond_txt,
                "condicao_icone": selecionar_icone(cond_txt),
                "probabilidade_chuva": pprob[i],
            })

        cache.set(cache_key, previsao, _ttl_with_jitter(ttl_segundos))
        cache.set(lkg_key, previsao, LKG_TTL_SECONDS)
        return previsao, False
    finally:
        _release_lock(lock_key)

# ========================== Helpers de status/tooltip das APIs ==========================
def _status_climatempo(cidade_id: int) -> dict:
    ns_cur, ns_prev = f"clima_atual:{cidade_id}", f"previsao_15:{cidade_id}"
    snoozed = _is_snoozed(ns_cur) or _is_snoozed(ns_prev)
    cur_fresh, prev_fresh = bool(cache.get(ns_cur)), bool(cache.get(ns_prev))
    cur_lkg, prev_lkg = cache.get(_lkg_key(ns_cur)), cache.get(_lkg_key(ns_prev))

    if cur_fresh and prev_fresh:
        state = "OK"
    elif snoozed:
        state = "LIMITADO"   # rate limit / Retry-After ativo
    elif cur_lkg or prev_lkg:
        state = "DEGRADADO"  # servindo LKG
    else:
        state = "OFFLINE"

    last_ok = None
    for src in (cache.get(ns_cur), cur_lkg):
        if isinstance(src, dict) and src.get("data"):
            last_ok = src["data"]; break

    return {"state": state, "snoozed": snoozed, "last_ok": last_ok}

def _status_openmeteo(lat: float, lon: float) -> dict:
    ns_cur = f"openmeteo_atual:{lat:.4f},{lon:.4f}"
    ns_prev = f"openmeteo_15:{lat:.4f},{lon:.4f}"
    cur_fresh, prev_fresh = bool(cache.get(ns_cur)), bool(cache.get(ns_prev))
    cur_lkg, prev_lkg = cache.get(_lkg_key(ns_cur)), cache.get(_lkg_key(ns_prev))

    if cur_fresh and prev_fresh:
        state = "OK"
    elif cur_lkg or prev_lkg:
        state = "DEGRADADO"
    else:
        state = "DESCONHECIDO"

    last_ok = None
    for src in (cache.get(ns_cur), cur_lkg):
        if isinstance(src, dict) and src.get("data"):
            last_ok = src["data"]; break

    return {"state": state, "last_ok": last_ok}

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
        try:
            request.session[f"form_last_show_{f.pk}"] = agora.isoformat()
            request.session.modified = True
        except Exception:
            pass
        break

    # --------- Clima (com LKG e circuit breaker) ---------
    cidade_id = getattr(settings, "CLIMATEMPO_CIDADE_ID", 5585)  # Carazinho, RS
    api_key = getattr(settings, "CLIMATEMPO_TOKEN", None)

    # Open-Meteo coords/timezone (fallback sem key)
    om_lat = float(getattr(settings, "OPENMETEO_LAT", -28.28389))
    om_lon = float(getattr(settings, "OPENMETEO_LON", -52.78639))
    om_tz  = getattr(settings, "OPENMETEO_TIMEZONE", getattr(settings, "TIME_ZONE", "America/Sao_Paulo"))

    clima_atual, clima_stale = (None, False)
    previsao_list, previsao_stale = (None, False)
    provider = None

    # 1) Tenta Climatempo se houver token
    if api_key:
        clima_atual, clima_stale = obter_clima_atual(cidade_id, api_key)
        previsao_list, previsao_stale = obter_previsao_15_dias(cidade_id, api_key)
        if clima_atual and previsao_list:
            provider = "climatempo"

    # 2) Fallback automático para Open-Meteo se não houver dados válidos
    if not clima_atual or not previsao_list:
        om_atual, om_stale = obter_clima_atual_openmeteo(om_lat, om_lon, om_tz)
        om_prev,  om_prev_stale = obter_previsao_openmeteo_15(om_lat, om_lon, om_tz)
        if om_atual and om_prev:
            clima_atual, clima_stale = om_atual, om_stale
            previsao_list, previsao_stale = om_prev, om_prev_stale
            provider = "openmeteo"

    dia_atual = int(request.GET.get('dia', 0) or 0)
    if dia_atual < 0:
        dia_atual = 0

    erro = ''
    previsao_atual = None

    if clima_atual and previsao_list:
        if 0 <= dia_atual < len(previsao_list):
            previsao_atual = previsao_list[dia_atual]
        else:
            previsao_atual = previsao_list[0]
            dia_atual = 0
    else:
        erro = 'Erro ao obter dados do tempo (limite da API ou conexão).'

    # --- Status das APIs para tooltip
    ct_status = _status_climatempo(cidade_id)
    om_status = _status_openmeteo(om_lat, om_lon)

    usando = "Climatempo" if provider == "climatempo" else ("Open-Meteo" if provider == "openmeteo" else "—")
    ct_line = f"Climatempo: {ct_status['state']}"
    if ct_status.get("snoozed"):
        ct_line += " (rate limit)"
    if ct_status.get("last_ok"):
        ct_line += f" • último ok: {ct_status['last_ok']}"
    om_line = f"Open-Meteo: {om_status['state']}"
    if om_status.get("last_ok"):
        om_line += f" • último ok: {om_status['last_ok']}"
    api_tooltip = f"Usando: {usando} | {ct_line} | {om_line}"

    context = {
        'clima_atual': clima_atual,
        'clima_stale': clima_stale,
        'previsao': previsao_atual,     # dado do dia selecionado
        'previsao_stale': previsao_stale,
        'dia_atual': dia_atual,
        'erro': erro,
        'form_popup': form_popup,
        'provider': provider,
        'api_tooltip': api_tooltip,
    }

    logger.debug(
        "HOME ctx: popup=%s, dia=%s, erro=%s, stale=(%s,%s), provider=%s, tooltip=%s",
        getattr(form_popup, "pk", None),
        dia_atual,
        bool(erro),
        clima_stale,
        previsao_stale,
        provider,
        api_tooltip,
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

def ideias_protagonistas(request):
    return render(request, 'ideias_protagonistas.html')
