import requests

def obter_previsao_completa(cidade_id='5585', api_key='5f713c18b31aee4d7a93df6a3220cfb8'):
    url_previsao = f"https://apiadvisor.climatempo.com.br/api/v1/forecast/locale/{cidade_id}/days/15?token={api_key}"
    
    try:
        resposta = requests.get(url_previsao)
        resposta.raise_for_status()  # Verifica se houve algum erro na requisição
        dados = resposta.json()

        # Processar dados da previsão de hoje
        previsao_atual = dados['data'][0]  # Pega o primeiro dia (hoje)

        # Verificar se existe um campo de temperatura atual
        temperatura_atual = None
        if 'temperature' in previsao_atual and 'current' in previsao_atual['temperature']:
            temperatura_atual = previsao_atual['temperature']['current']  # Verifica temperatura atual

        previsao_15_dias = []
        for dia in dados.get('data', []):
            previsao_15_dias.append({
                'data': dia['date_br'],
                'temperatura_min': dia['temperature']['min'],
                'temperatura_max': dia['temperature']['max'],
                'condicao': dia['text_icon']['text']['phrase']['reduced'],
                'probabilidade_chuva': dia['rain']['probability'],
                'icone': dia['text_icon']['icon']['day']  # Ícone do clima para o dia
            })

        return {
            'temperatura_atual': temperatura_atual,
            'previsao_atual': previsao_atual,
            'previsao_15_dias': previsao_15_dias
        }

    except requests.exceptions.RequestException as e:
        print(f"Erro ao obter a previsão: {e}")
        return None
