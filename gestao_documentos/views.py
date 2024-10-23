from django.shortcuts import render
import requests
import time

# Variáveis para armazenar o cache e o tempo da última atualização
previsao_cache = None
ultima_atualizacao = 0

# Função para obter clima atual
def obter_clima_atual(cidade_id, api_key):
    url_atual = f"https://apiadvisor.climatempo.com.br/api/v1/weather/locale/{cidade_id}/current?token={api_key}"
    try:
        resposta = requests.get(url_atual)
        resposta.raise_for_status()
        dados = resposta.json()
        clima_atual = {
            'temperatura_atual': dados['data']['temperature'],
            'sensacao': dados['data']['sensation'],
            'humidade': dados['data']['humidity'],
            'condicao': dados['data']['condition'],
            'icone': selecionar_icone(dados['data']['condition']),
            'data': dados['data']['date']
        }
        return clima_atual
    except requests.exceptions.RequestException as e:
        print(f"Erro ao obter clima atual: {e}")
        return None

# Função para a previsão de 15 dias com cache
def obter_previsao_15_dias(cidade_id, api_key, intervalo_cache=3600):
    global previsao_cache, ultima_atualizacao
    
    # Se já passou o tempo do cache ou o cache está vazio, faz uma nova requisição
    if time.time() - ultima_atualizacao > intervalo_cache or previsao_cache is None:
        url_previsao = f"https://apiadvisor.climatempo.com.br/api/v1/forecast/locale/{cidade_id}/days/15?token={api_key}"
        try:
            resposta = requests.get(url_previsao)
            resposta.raise_for_status()
            dados = resposta.json()
            previsao = []
            for dia in dados.get('data', []):
                condicao_clima = dia['text_icon']['text']['phrase']['reduced']
                print(f"Condição do clima retornada pela API: {condicao_clima}")
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
        except requests.exceptions.RequestException as e:
            if resposta.status_code == 429:
                print(f"Erro: Limite de requisições atingido. Tente novamente mais tarde.")
            else:
                print(f"Erro ao obter previsão: {e}")
            return None
    
    return previsao_cache

# View da home
def home(request):
    cidade_id = 5585  # Carazinho, RS
    api_key = '0e757fa29362163506c6cb24d14f10cf'
    
    # Obter clima atual e previsão com cache
    clima_atual = obter_clima_atual(cidade_id, api_key)
    previsao = obter_previsao_15_dias(cidade_id, api_key)

    if clima_atual and previsao:
        dia_atual = int(request.GET.get('dia', 0))  # Controle dos dias na previsão
        previsao_atual = previsao[dia_atual] if dia_atual < len(previsao) else previsao[0]
        
        return render(request, 'home.html', {
            'clima_atual': clima_atual,
            'previsao': previsao_atual,
            'dia_atual': dia_atual,
        })
    else:
        return render(request, 'home.html', {'erro': 'Erro ao obter dados do tempo.'})

# Função para mapear a condição ao ícone
def selecionar_icone(condicao):
    condicao_map = {
        'sol com algumas nuvens': '2',  # Sol com algumas nuvens
        'sol com muitas nuvens': '2r',  # Sol com muitas nuvens
        'sol': '1',  # Sol
        'noite sem nuvens': '1n',  # Noite sem nuvens
        'noite com algumas nuvens': '2n',  # Noite com algumas nuvens
        'noite com muitas nuvens': '2rn',  # Noite com muitas nuvens
        'nublado': '3',  # Nublado
        'sol e chuva': '4',  # Sol e chuva
        'sol com muitas nuvens e chuva': '4r',  # Sol com muitas nuvens e chuva
        'noite chuvosa': '4n',  # Noite chuvosa
        'noite nublada e chuvosa': '4rn',  # Noite nublada e chuvosa
        'sol entre nuvens e pancadas de chuva, com trovoadas': '4t',  # Sol com pancadas de chuva e trovoadas
        'pancadas de chuva durante a noite': '4tn',  # Pancadas de chuva à noite
        'chuvoso': '5',  # Chuvoso
        'chuva e trovoadas': '6',  # Chuva e trovoadas
        'geada': '7',  # Geada
        'neve': '8',  # Neve
        'nevoeiro': '9',  # Nevoeiro
    }

    # Normaliza a condição para letras minúsculas e sem acentuação
    condicao_normalizada = condicao.lower()

    # Procura pela condição exata no dicionário
    for chave, icone in condicao_map.items():
        if chave in condicao_normalizada:
            return icone
    
    # Caso não encontre, retorna um ícone padrão
    return 'default'
