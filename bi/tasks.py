# bi/tasks.py
import logging
import datetime # <<< ADICIONAR ESTE IMPORT
from celery import shared_task
from django.conf import settings
from django.utils import timezone # django.utils.timezone ainda é usado para get_current_timezone, localtime, etc.
from django.utils.dateparse import parse_datetime
import requests

# from .models import BIReport # Descomente se não estiver fazendo import tardio
# from .utils import get_powerbi_access_token # Descomente se não estiver fazendo import tardio

logger = logging.getLogger(__name__) # Ou getLogger('bi') se você alterou anteriormente

def _get_dataset_last_refresh_time(dataset_id: str, dataset_group_id: str, access_token: str) -> timezone.datetime | None:
    if not dataset_id:
        logger.warning("PBI API Call: _get_dataset_last_refresh_time - dataset_id não fornecido.")
        return None
    if not dataset_group_id:
        logger.warning(f"PBI API Call: _get_dataset_last_refresh_time - dataset_group_id não fornecido para dataset_id '{dataset_id}'.")
        return None

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{dataset_group_id}/datasets/{dataset_id}/refreshes?$top=1"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    logger.info(f"PBI API Call: Tentando obter histórico de atualização para Dataset ID '{dataset_id}' no Group ID '{dataset_group_id}'. URL: {url}")
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        logger.debug(f"PBI API Call: Dataset ID '{dataset_id}'. Status da Resposta: {resp.status_code}")

        if resp.status_code != 200:
            error_text = resp.text[:500] if resp.text else "Sem corpo de resposta."
            logger.error(f"PBI API Call: Falha para Dataset ID '{dataset_id}'. Status: {resp.status_code}, Resposta: {error_text}")
            resp.raise_for_status()

        refreshes_data = resp.json()
        logger.debug(f"PBI API Call: Dataset ID '{dataset_id}'. JSON da Resposta: {refreshes_data}")
        refreshes = refreshes_data.get("value", [])
        
        if refreshes:
            latest_refresh = refreshes[0]
            logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Entrada de atualização mais recente: {latest_refresh}")
            status = latest_refresh.get("status")
            end_time_str = latest_refresh.get("endTime")
            start_time_str = latest_refresh.get("startTime")

            target_time_str = None
            parsed_dt = None

            if status == "Completed" and end_time_str:
                target_time_str = end_time_str
            elif status == "Unknown":
                logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Status da atualização é 'Unknown'. Tentando endTime '{end_time_str}', depois startTime '{start_time_str}'.")
                target_time_str = end_time_str if end_time_str else start_time_str
            else:
                logger.warning(f"PBI API Call: Dataset ID '{dataset_id}'. Status da última atualização é '{status}' (esperado 'Completed' ou 'Unknown' com data válida). EndTime: '{end_time_str}'.")
                return None

            if target_time_str:
                logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Tentando parsear string de data/hora: '{target_time_str}'")
                parsed_dt = parse_datetime(target_time_str)
                if parsed_dt:
                    logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Data/hora parseada com sucesso: {parsed_dt}")
                    
                    aware_dt = parsed_dt
                    if timezone.is_naive(parsed_dt):
                        # Tornar ciente usando datetime.timezone.utc
                        aware_dt = parsed_dt.replace(tzinfo=datetime.timezone.utc) # Correção aqui também, ou make_aware
                        # Ou, se preferir usar make_aware (que é mais robusto para ambiguidades de DST, embora menos relevante para UTC puro):
                        # aware_dt = timezone.make_aware(parsed_dt, datetime.timezone.utc) 
                        logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Data/hora tornada ciente do fuso (UTC): {aware_dt}")
                    else: 
                        # Se já for aware, garantir que seja UTC
                        aware_dt = aware_dt.astimezone(datetime.timezone.utc) # <<< CORRIGIDO AQUI
                        logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Data/hora já está ciente do fuso, convertida/confirmada para UTC: {aware_dt}")

                    if not settings.USE_TZ:
                        try:
                            local_tz = timezone.get_current_timezone() 
                            naive_local_dt = timezone.localtime(aware_dt, local_tz).replace(tzinfo=None)
                            logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Convertido para datetime naive local ({local_tz}): {naive_local_dt} (devido a USE_TZ=False).")
                            return naive_local_dt
                        except Exception as e_tz_conv:
                            logger.error(f"PBI API Call: Dataset ID '{dataset_id}'. Erro ao converter datetime aware para naive local: {e_tz_conv}", exc_info=True)
                            return None 
                    
                    return aware_dt # Retorna datetime "aware" (UTC) se USE_TZ=True
                else:
                    logger.error(f"PBI API Call: Dataset ID '{dataset_id}'. Falha ao parsear string de data/hora: '{target_time_str}'.")
                    return None
            else:
                logger.warning(f"PBI API Call: Dataset ID '{dataset_id}'. Nenhuma string de data/hora utilizável (endTime ou startTime) encontrada para o status '{status}'.")
                return None
        else:
            logger.info(f"PBI API Call: Dataset ID '{dataset_id}'. Nenhum histórico de atualização encontrado (API retornou lista 'value' vazia).")
            return None
            
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"PBI API Call: Erro HTTP para Dataset ID '{dataset_id}' durante busca de histórico de atualização – {http_err}")
    except requests.exceptions.RequestException as req_exc:
        logger.error(f"PBI API Call: Erro de Request para Dataset ID '{dataset_id}' durante busca de histórico de atualização – {req_exc}")
    except Exception as e:
        logger.error(f"PBI API Call: Erro genérico para Dataset ID '{dataset_id}' ao processar dados de atualização – {e}", exc_info=True)
        
    return None


def _listar_relatorios(group_id: str, access_token: str) -> list[dict] | None:
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports"
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.info(f"PBI API Call: Listando relatórios para Group ID '{group_id}'. URL: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        logger.debug(f"PBI API Call: Listar relatórios. Status da Resposta: {resp.status_code}")
        if resp.status_code != 200:
            error_text = resp.text[:500] if resp.text else "Sem corpo de resposta."
            logger.error(f"PBI API Call: Falha ao listar relatórios para Group ID '{group_id}'. Status: {resp.status_code}, Resposta: {error_text}")
            resp.raise_for_status()
        return resp.json().get("value", [])
    except requests.exceptions.RequestException as exc:
        logger.error(f"PBI API Call: Erro de Request ao listar relatórios para Group ID '{group_id}' – {exc}")
        return None
    except Exception as e:
        logger.error(f"PBI API Call: Erro genérico ao listar relatórios para Group ID '{group_id}' – {e}", exc_info=True)
        return None


@shared_task
def sincronizar_bi_reports():
    from .models import BIReport
    from .utils import get_powerbi_access_token

    logger.info("Tarefa BI: Iniciando sincronização de relatórios.")
    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("Tarefa BI: Falha ao obter access_token. Sincronização abortada.")
        return

    report_workspace_id_from_settings = settings.POWERBI_GROUP_ID_DEFAULT
    api_reports_list = _listar_relatorios(report_workspace_id_from_settings, access_token)
    
    if api_reports_list is None:
        logger.error("Tarefa BI: Não foi possível listar relatórios da API. Sincronização abortada.")
        return
    if not api_reports_list:
        logger.info("Tarefa BI: Nenhum relatório encontrado na API para o workspace configurado. Nada a sincronizar.")
        return

    reports_processed_count = 0
    for report_data_from_api in api_reports_list:
        reports_processed_count += 1
        
        report_id_pbi = report_data_from_api.get("id")
        report_name_pbi = report_data_from_api.get("name", f"RelatorioSemNome_{report_id_pbi or 'ID_Desconhecido'}")
        dataset_id_pbi = report_data_from_api.get("datasetId")
        
        logger.info(f"Processando Relatório: '{report_name_pbi}' (ID PBI: {report_id_pbi})")

        report_actual_workspace_id = report_data_from_api.get("groupId", report_workspace_id_from_settings)
        dataset_actual_workspace_id = report_data_from_api.get("datasetWorkspaceId")
        group_id_for_dataset_api_call = dataset_actual_workspace_id if dataset_actual_workspace_id else report_actual_workspace_id
        
        logger.info(f"  Detalhes - DatasetID: '{dataset_id_pbi}', Workspace do Relatório: '{report_actual_workspace_id}', Workspace do Dataset para API: '{group_id_for_dataset_api_call}'")

        power_bi_data_refresh_time = None
        if dataset_id_pbi and group_id_for_dataset_api_call:
            power_bi_data_refresh_time = _get_dataset_last_refresh_time(
                dataset_id_pbi, 
                group_id_for_dataset_api_call, 
                access_token
            )
        elif not dataset_id_pbi:
             logger.info(f"  Relatório '{report_name_pbi}' não possui datasetId. Pulando busca de data de atualização do PBI.")
        elif not group_id_for_dataset_api_call:
             logger.warning(f"  Relatório '{report_name_pbi}' (Dataset: {dataset_id_pbi}): group_id_for_dataset_api_call está faltando ou é inválido. Pulando busca de data de atualização do PBI.")

        logger.info(f"  Data de atualização PBI (processada) obtida para '{report_name_pbi}': {power_bi_data_refresh_time}")

        current_defaults = {
            "title": report_name_pbi,
            "embed_code": report_data_from_api.get("embedUrl", ""),
            "group_id": report_actual_workspace_id,
            "dataset_id": dataset_id_pbi,
        }

        try:
            bi_report_obj, created = BIReport.objects.update_or_create(
                report_id=report_id_pbi,
                defaults=current_defaults
            )

            log_action_prefix = "Criado" if created else "Atualizado (metadados)"
            logger.info(f"  {log_action_prefix} registro do relatório '{bi_report_obj.title}' no BD local.")

            updated_field_in_db = False
            if power_bi_data_refresh_time:
                if bi_report_obj.last_updated != power_bi_data_refresh_time:
                    bi_report_obj.last_updated = power_bi_data_refresh_time
                    bi_report_obj.save(update_fields=['last_updated']) # Este save agora deve funcionar
                    updated_field_in_db = True
                    logger.info(f"  SUCESSO: 'last_updated' do relatório '{bi_report_obj.title}' ATUALIZADO no BD para data PBI: {power_bi_data_refresh_time}.")
                else:
                    logger.info(f"  INFO: 'last_updated' do relatório '{bi_report_obj.title}' ({bi_report_obj.last_updated}) já corresponde à data PBI ({power_bi_data_refresh_time}). Nenhuma alteração em 'last_updated'.")
            elif created: 
                if bi_report_obj.last_updated is not None:
                    bi_report_obj.last_updated = None
                    bi_report_obj.save(update_fields=['last_updated'])
                    updated_field_in_db = True
                    logger.info(f"  INFO: Relatório novo '{bi_report_obj.title}'. Data PBI não encontrada. 'last_updated' definido como None no BD.")
                else:
                    logger.info(f"  INFO: Relatório novo '{bi_report_obj.title}'. Data PBI não encontrada. 'last_updated' já é None.")
            else: 
                current_lu_display = bi_report_obj.last_updated.strftime("%Y-%m-%d %H:%M:%S") if bi_report_obj.last_updated else "None"
                logger.info(f"  INFO: Relatório existente '{bi_report_obj.title}'. Data PBI não encontrada nesta sincronização. 'last_updated' ({current_lu_display}) permanece inalterado no BD.")
            
            if not updated_field_in_db and not created:
                 logger.info(f"  INFO: Relatório existente '{bi_report_obj.title}'. Nenhuma alteração em 'last_updated' ou metadados básicos nesta sincronização.")

        except Exception as db_exc: # Captura qualquer erro durante o update_or_create ou o save subsequente
            logger.error(f"  ERRO DB: Falha ao criar/atualizar relatório '{report_name_pbi}' (ID PBI: {report_id_pbi}) no banco de dados: {db_exc}", exc_info=True)
            continue 

    logger.info(f"Tarefa BI: Sincronização concluída. {reports_processed_count} relatórios da API foram processados.")