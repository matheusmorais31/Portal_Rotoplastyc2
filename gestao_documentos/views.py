# views.py

from django.shortcuts import render
import requests
import time
import logging

logger = logging.getLogger(__name__)

# Variáveis para armazenar o cache e o tempo da última atualização
previsao_cache = None
ultima_atualizacao = 0

# Função para mapear a condição ao ícone
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
        'muitas nuvens': '3'


    }

    condicao_normalizada = condicao.lower()

    for chave, icone in condicao_map.items():
        if chave in condicao_normalizada:
            return icone

    return 'default'

# Função para obter o clima atual
def obter_clima_atual(cidade_id, api_key):
    url_atual = f"https://apiadvisor.climatempo.com.br/api/v1/weather/locale/{cidade_id}/current?token={api_key}"
    try:
        resposta = requests.get(url_atual)
        resposta.raise_for_status()
        dados = resposta.json()
        condicao_clima = dados['data']['condition']
        print(f"Condição climática recebida: {condicao_clima}")  # Adicione esta linha
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

# Função para obter a previsão de 15 dias com cache
def obter_previsao_15_dias(cidade_id, api_key, intervalo_cache=3600):
    global previsao_cache, ultima_atualizacao

    if time.time() - ultima_atualizacao > intervalo_cache or previsao_cache is None:
        url_previsao = f"https://apiadvisor.climatempo.com.br/api/v1/forecast/locale/{cidade_id}/days/15?token={api_key}"
        try:
            resposta = requests.get(url_previsao)
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

# View da home
def home(request):
    cidade_id = 5585  # Carazinho, RS
    api_key = '5f713c18b31aee4d7a93df6a3220cfb8'  # Substitua pela sua chave de API

    # Obter clima atual e previsão com cache
    clima_atual = obter_clima_atual(cidade_id, api_key)
    previsao = obter_previsao_15_dias(cidade_id, api_key)

    dia_atual = int(request.GET.get('dia', 0))  # Controle dos dias na previsão

    # Impedir dias negativos
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
    }

    logger.debug(f"Contexto enviado para o template: {context}")

    return render(request, 'home.html', context)
