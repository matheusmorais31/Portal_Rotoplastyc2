import logging
import requests
from datetime import datetime, timedelta
import pytz
from django.conf import settings
import msal
from .models import BIReport

logger = logging.getLogger(__name__)

# Mapeamento de Timezone do Windows para IANA
WINDOWS_TO_IANA = {
    'E. South America Standard Time': 'America/Sao_Paulo',
    # Adicione outros mapeamentos conforme necessário
}

def acquire_access_token():
    """
    Adquire um token de acesso usando a biblioteca MSAL.
    Utiliza cache para evitar aquisições excessivas de token.
    """
    cached_token = cache_get_access_token()
    if cached_token:
        logger.debug("Token de acesso recuperado do cache.")
        return cached_token

    authority = f'https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}'
    scopes = ['https://analysis.windows.net/powerbi/api/.default']

    try:
        app = msal.ConfidentialClientApplication(
            client_id=settings.POWERBI_CLIENT_ID,
            authority=authority,
            client_credential=settings.POWERBI_CLIENT_SECRET
        )
        result = app.acquire_token_for_client(scopes=scopes)
        logger.debug(f"Resultado da aquisição do token: {result}")

        if 'access_token' in result:
            access_token = result['access_token']
            expires_in = result.get('expires_in', 3600)  # Default para 1 hora
            cache_set_access_token(access_token, expires_in)
            return access_token
        else:
            logger.error("Falha ao adquirir o token de acesso")
            logger.error(f"Erro: {result.get('error')}, Descrição: {result.get('error_description')}")
            return None
    except Exception as e:
        logger.exception("Exceção ao adquirir token com MSAL")
        return None

def cache_get_access_token():
    """
    Recupera o token de acesso do cache.
    """
    try:
        from django.core.cache import cache
        return cache.get('powerbi_access_token')
    except Exception as e:
        logger.error(f"Erro ao acessar o cache: {e}")
        return None

def cache_set_access_token(token, expires_in):
    """
    Armazena o token de acesso no cache.
    """
    try:
        from django.core.cache import cache
        # Armazena o token 5 minutos antes de expirar
        cache.set('powerbi_access_token', token, timeout=expires_in - 300)
        logger.debug("Token de acesso armazenado no cache.")
    except Exception as e:
        logger.error(f"Erro ao definir o cache: {e}")

def get_dataset_refresh_info(dataset_id, group_id, access_token):
    """
    Obtém informações de refresh do dataset, incluindo a última e a próxima atualização.
    """
    refreshes_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/datasets/{dataset_id}/refreshes?$top=1&$orderby=endTime desc"
    headers = {'Authorization': f'Bearer {access_token}'}
    
    logger.info(f"Obtendo informações de refresh para dataset_id={dataset_id} no group_id={group_id}")
    
    try:
        response = requests.get(refreshes_url, headers=headers)
        logger.debug(f"Código de status da resposta de refresh: {response.status_code}")
        logger.debug(f"Conteúdo da resposta de refresh: {response.text}")
        
        if response.status_code == 200:
            refreshes = response.json().get('value', [])
            if refreshes:
                latest_refresh = refreshes[0]
                # Extrair 'endTime' como a data de última atualização
                last_refresh_str = latest_refresh.get('endTime')
                last_refresh_dt = convert_to_local_timezone(last_refresh_str)
                logger.info(f"Última atualização para dataset_id={dataset_id}: {last_refresh_dt}")
                
                # Obter a programação de refresh
                schedule = get_dataset_refresh_schedule(dataset_id, group_id, access_token)
                next_refresh = get_next_refresh(schedule, last_refresh_dt)
                logger.info(f"Próxima atualização para dataset_id={dataset_id}: {next_refresh}")
                
                return last_refresh_dt, next_refresh
            else:
                logger.warning(f"Nenhuma informação de refresh encontrada para o dataset ID={dataset_id}.")
                return None, None
        else:
            logger.error(f"Erro ao obter informações de refresh: {response.status_code} - {response.text}")
            return None, None
    except Exception as e:
        logger.exception(f"Exceção ao obter informações de refresh para o dataset ID={dataset_id}: {e}")
        return None, None

def get_dataset_refresh_schedule(dataset_id, group_id, access_token):
    """
    Obtém a programação de refresh para o dataset.
    """
    schedule_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/datasets/{dataset_id}/refreshSchedule"
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        response = requests.get(schedule_url, headers=headers)
        logger.debug(f"Código de status da resposta de schedule: {response.status_code}")
        logger.debug(f"Conteúdo da resposta de schedule: {response.text}")
        
        if response.status_code == 200:
            schedule = response.json()
            return schedule
        else:
            logger.error(f"Erro ao obter schedule de refresh: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.exception(f"Exceção ao obter schedule de refresh para o dataset ID={dataset_id}: {e}")
        return None

def convert_to_local_timezone(time_str):
    """
    Converte uma string de data/hora em UTC para a timezone local.
    """
    if not time_str:
        return None
    try:
        # Tenta converter com microsegundos
        dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        try:
            # Tenta converter sem microsegundos
            dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as e:
            logger.error(f"Erro ao converter '{time_str}' para datetime: {e}")
            return None
    dt = dt.replace(tzinfo=pytz.UTC)
    
    # Mapeia o timezone se necessário
    local_timezone = settings.TIME_ZONE
    if local_timezone in WINDOWS_TO_IANA:
        local_timezone = WINDOWS_TO_IANA[local_timezone]
    
    try:
        return dt.astimezone(pytz.timezone(local_timezone))
    except pytz.UnknownTimeZoneError as e:
        logger.error(f"Timezone desconhecida '{local_timezone}': {e}")
        return None

def get_next_refresh(schedule, last_refresh):
    """
    Calcula a próxima data de refresh com base na programação e na última atualização.
    
    :param schedule: Dicionário com a programação de refresh.
    :param last_refresh: Objeto datetime da última atualização.
    :return: Objeto datetime da próxima atualização ou None.
    """
    if not schedule or not schedule.get('enabled'):
        return None

    days = schedule.get('days', [])
    times = schedule.get('times', [])
    timezone_id = schedule.get('localTimeZoneId', 'UTC')
    
    # Mapeia o timezone se necessário
    if timezone_id in WINDOWS_TO_IANA:
        timezone_id = WINDOWS_TO_IANA[timezone_id]
    
    try:
        tz = pytz.timezone(timezone_id)
    except pytz.UnknownTimeZoneError as e:
        logger.error(f"Timezone desconhecida '{timezone_id}': {e}")
        return None
    
    # Se a última atualização estiver disponível, basear a próxima atualização nela
    if last_refresh:
        last_refresh = last_refresh.astimezone(tz)
        next_refresh = last_refresh + timedelta(days=1)
    else:
        next_refresh = datetime.now(tz)
    
    # Encontrar o próximo dia da semana que está na programação
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for _ in range(7):  # Limite para evitar loops infinitos
        day_name = weekdays[next_refresh.weekday()]
        if day_name in days:
            for time_str in times:
                try:
                    hour, minute = map(int, time_str.split(':'))
                except ValueError as e:
                    logger.error(f"Erro ao parsear time_str '{time_str}': {e}")
                    continue
                scheduled_time = next_refresh.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if scheduled_time > last_refresh:
                    return scheduled_time
        next_refresh += timedelta(days=1)
    
    return None

def get_powerbi_reports(group_id, access_token):
    """
    Obtém a lista de relatórios do Power BI no workspace especificado,
    incluindo a última data de atualização e a próxima atualização do dataset.
    Retorna os dados dos relatórios para processamento posterior.
    """
    logger.info("Iniciando get_powerbi_reports")

    headers = {'Authorization': f'Bearer {access_token}'}

    # Endpoint para listar relatórios
    reports_url = f'https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports'
    logger.info(f"Requisitando lista de relatórios: {reports_url}")
    try:
        response = requests.get(reports_url, headers=headers)
        logger.debug(f"Código de status da resposta: {response.status_code}")
        logger.debug(f"Conteúdo da resposta: {response.text}")
    except Exception as e:
        logger.exception("Exceção ao requisitar lista de relatórios")
        return None

    if response.status_code != 200:
        logger.error(f"Erro ao obter lista de relatórios: {response.status_code} - {response.text}")
        return None

    reports = response.json().get('value', [])
    logger.info(f"Quantidade de relatórios encontrados: {len(reports)}")

    for report in reports:
        report_id = report.get('id')
        report_name = report.get('name')
        dataset_id = report.get('datasetId')  # Obtém o dataset_id do relatório
        embed_url = report.get('embedUrl')
        dataset_workspace_id = report.get('datasetWorkspaceId')

        logger.debug(f"Relatório: ID={report_id}, Nome={report_name}, DatasetWorkspaceId={dataset_workspace_id}")

        if not dataset_workspace_id:
            logger.error(f"Relatório '{report_name}' não possui 'datasetWorkspaceId'.")
            continue  # Pular este relatório

        if dataset_id:
            # Obter informações de refresh (última e próxima atualização)
            last_refresh, next_refresh = get_dataset_refresh_info(dataset_id, dataset_workspace_id, access_token)

            # last_refresh and next_refresh são objetos datetime ou None
            logger.debug(f"Dataset ID={dataset_id}: last_refresh={last_refresh}, next_refresh={next_refresh}")

            # Atualizar ou criar o BIReport no banco de dados
            try:
                bi_report, created = BIReport.objects.update_or_create(
                    report_id=report_id,
                    defaults={
                        'title': report_name,
                        'embed_code': embed_url,
                        'group_id': dataset_workspace_id,
                        'dataset_id': dataset_id,  # Armazena o dataset_id
                        'last_updated': last_refresh,
                        'next_update': next_refresh,
                    }
                )
                if created:
                    logger.info(f"Relatório '{bi_report.title}' criado no banco de dados.")
                else:
                    logger.info(f"Relatório '{bi_report.title}' atualizado no banco de dados.")
            except Exception as e:
                logger.error(f"Erro ao atualizar/criar o relatório '{report_name}': {e}")
        else:
            logger.warning(f"Relatório '{report_name}' não possui 'datasetId'.")

    return reports

def get_powerbi_embed_params(report_id, group_id, dataset_id, user_id, username, roles=None):
    """
    Gera os parâmetros necessários para embutir um relatório Power BI.
    
    Args:
        report_id (str): ID do relatório Power BI.
        group_id (str): ID do grupo (workspace) do Power BI.
        dataset_id (str): ID do dataset relacionado ao relatório.
        user_id (int): ID único do usuário.
        username (str): Nome de usuário.
        roles (list, optional): Lista de roles atribuídas ao usuário.
    
    Returns:
        dict: Contém 'embed_url' e 'embed_token'.
    """
    authority_url = f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}"
    client_id = settings.POWERBI_CLIENT_ID
    client_secret = settings.POWERBI_CLIENT_SECRET
    scope = ["https://analysis.windows.net/powerbi/api/.default"]

    try:
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority_url,
            client_credential=client_secret,
        )

        token_response = app.acquire_token_for_client(scopes=scope)

        if "access_token" in token_response:
            access_token = token_response['access_token']
            
            # 1. Obter o embedUrl via GET
            report_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}"
            logger.debug(f"Requisitando detalhes do relatório: {report_url}")
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            report_response = requests.get(report_url, headers=headers)
            logger.debug(f"Código de status da resposta do relatório: {report_response.status_code}")
            logger.debug(f"Conteúdo da resposta do relatório: {report_response.text}")

            if report_response.status_code != 200:
                logger.error(f"Erro ao obter detalhes do relatório: {report_response.status_code} - {report_response.text}")
                return None

            report_data = report_response.json()
            embed_url = report_data.get('embedUrl')
            if not embed_url:
                logger.error("embedUrl não encontrado na resposta do relatório.")
                return None

            # 2. Gerar o embed token via POST
            embed_token_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}/GenerateToken"

            # Payload sem effective identity para app owns data
            payload = {
                "accessLevel": "view"
                # Removido 'identities' para evitar o erro de InvalidRequest
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }

            logger.debug(f"Solicitando embed token: {embed_token_url} com payload: {payload}")
            embed_response = requests.post(embed_token_url, json=payload, headers=headers)
            logger.debug(f"Código de status da resposta de embed token: {embed_response.status_code}")
            logger.debug(f"Conteúdo da resposta de embed token: {embed_response.text}")

            if embed_response.status_code == 200:
                embed_data = embed_response.json()
                embed_token = embed_data.get('token')
                if not embed_token:
                    logger.error("embed_token não encontrado na resposta do embed token.")
                    return None
                return {
                    'embed_url': embed_url,
                    'embed_token': embed_token
                }
            else:
                # Log detalhado do erro
                logger.error(f"Erro ao gerar embed token: {embed_response.status_code} - {embed_response.text}")
                return None
        else:
            logger.error("Erro ao adquirir token de acesso do Power BI.")
            return None
    except Exception as e:
        logger.exception(f"Exceção ao gerar embed token para o relatório ID={report_id}: {e}")
        return None

def get_powerbi_embed_params_with_token(report_id, group_id, access_token):
    """
    Gera os parâmetros necessários para embutir (embed) um relatório do Power BI,
    incluindo a geração do embed token.
    """
    embed_token_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}/GenerateToken"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    body = {
        "accessLevel": "view",
        "allowSaveAs": "false"
    }

    try:
        response = requests.post(embed_token_url, headers=headers, json=body)
        logger.debug(f"Código de status da resposta de embed token: {response.status_code}")
        logger.debug(f"Conteúdo da resposta de embed token: {response.text}")

        if response.status_code == 200:
            embed_data = response.json()
            embed_token = embed_data.get('token')
            # Obter a URL de embed do relatório
            report_embed_url = f"https://app.powerbi.com/reportEmbed?reportId={report_id}&groupId={group_id}&w=2&config=eyJjbHVzdGVyVXJsIjoiaHR0cHM6Ly9XQUJJLUJSQVpJTC1TT1VUSC1yZWRpcmVjdC5hbmFseXNpcy53aW5kb3dzLm5ldCIsImVtYmVkRmVhdHVyZXMiOnsidXNhZ2VNZXRyaWNzVk5leHQiOnRydWV9fQ%3d%3d"
            return {
                'embed_url': report_embed_url,
                'embed_token': embed_token
            }
        else:
            logger.error(f"Erro ao gerar embed token: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.exception(f"Exceção ao gerar embed token para o relatório ID={report_id}: {e}")
        return None