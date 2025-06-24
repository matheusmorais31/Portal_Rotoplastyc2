# ia/llm_toolkit.py
from __future__ import annotations
import json, os, re, subprocess, tempfile, textwrap, time, logging, difflib, unicodedata, csv
from pathlib import Path
from typing import List, Any 
import pandas as pd
import google.generativeai as genai

logger = logging.getLogger(__name__)

# --- Bloco de Inicialização de LLMs ---
openai, _OPENAI_V1, _oa_client = None, False, None
try:
    import openai
    _OPENAI_V1 = hasattr(openai, "OpenAI")
    if _OPENAI_V1: _oa_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    else:
        if os.getenv("OPENAI_API_KEY"): openai.api_key = os.getenv("OPENAI_API_KEY")
except ModuleNotFoundError: logger.info("Biblioteca 'openai' não encontrada.")
except Exception as e: logger.error(f"Erro ao inicializar OpenAI: {e}"); openai, _OPENAI_V1, _oa_client = None, False, None

def _norm(text_to_normalize: str) -> str:
    if not isinstance(text_to_normalize, str): text_to_normalize = str(text_to_normalize)
    nfkd_form = unicodedata.normalize('NFKD', text_to_normalize)
    normalized_text = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    try: ascii_text = normalized_text.encode('ascii', 'ignore').decode('ascii')
    except UnicodeEncodeError: ascii_text = normalized_text 
    processed_text = re.sub(r"[^\w_]+", "_", ascii_text.strip(), flags=re.A).upper()
    processed_text = re.sub(r"_+", "_", processed_text).strip("_")
    return processed_text or "COL"

def chat_openai(messages: list[dict], *, model: str = "gpt-4o-mini", temperature: float = 0.1) -> tuple[str, dict | None]:
    if not openai: raise RuntimeError("OpenAI não está configurado ou a biblioteca não foi importada.")
    if _OPENAI_V1 and (not _oa_client or not _oa_client.api_key): raise RuntimeError("OpenAI v1+ está configurado, mas a API Key está faltando ou é inválida.")
    if not _OPENAI_V1 and not openai.api_key: raise RuntimeError("OpenAI v0 está configurado, mas a API Key está faltando.")
    try:
        if _OPENAI_V1:
            rsp = _oa_client.chat.completions.create(model=model, messages=messages, temperature=temperature)
            text = rsp.choices[0].message.content.strip() if rsp.choices and rsp.choices[0].message else ""
            usage = rsp.usage.model_dump() if rsp.usage else None
        else:
            rsp = openai.ChatCompletion.create(model=model, messages=messages, temperature=temperature)
            text = rsp.choices[0].message.content.strip() if rsp.choices and rsp.choices[0].message else ""
            usage = rsp.usage.to_dict() if rsp.usage else None
        return text, usage
    except Exception as e: logger.error(f"Erro na API OpenAI ({model}): {e}", exc_info=True); raise

def chat_gemini(history: list[dict], *, model: str = "models/gemini-1.5-flash-latest", temperature: float = 0.1) -> tuple[str, object | None]:
    try:
        g_model = genai.GenerativeModel(model)
        rep = g_model.generate_content(history, generation_config=genai.types.GenerationConfig(temperature=temperature))
        text_content = rep.text if hasattr(rep, 'text') and rep.text is not None else ""
        if not text_content and hasattr(rep, 'candidates') and rep.candidates and rep.candidates[0].content and rep.candidates[0].content.parts:
            text_content = "".join(part.text for part in rep.candidates[0].content.parts if hasattr(part, 'text')).strip()
        usage_metadata = rep.usage_metadata if hasattr(rep, 'usage_metadata') else None
        return text_content.strip(), usage_metadata
    except Exception as e: logger.error(f"Erro na API Gemini ({model}): {e}", exc_info=True); raise

def _extract_json_candidate(txt: str) -> str | None:
    if "```" in txt:
        match_md_json = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.S)
        if match_md_json: return match_md_json.group(1)
        parts = [p for p in txt.split("```") if "{" in p and "}" in p]
        txt = parts[0] if parts else txt
    m = re.search(r"\{.*\}", txt, re.S)
    return m.group(0) if m else None

class LoadError(RuntimeError): ...
SOFFICE_BIN = Path(os.getenv("SOFFICE_PATH", "/usr/bin/soffice"))

def _convert_xls_like_to_csvs(src: Path) -> List[Path]:
    if not SOFFICE_BIN.exists(): raise LoadError(f"LibreOffice não encontrado em {SOFFICE_BIN}.")
    tmp_dir = Path(tempfile.mkdtemp(prefix="ia_csv_")); csv_filter = "csv:Text - txt - csv (StarCalc):59,34,76,-1"
    cmd = [str(SOFFICE_BIN), "--headless", "--convert-to", csv_filter, "--outdir", str(tmp_dir), str(src)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0: raise LoadError(f"Erro LibreOffice: {res.stderr[:1000]}")
    except subprocess.TimeoutExpired: raise LoadError(f"Timeout ao converter {src}.")
    except Exception as e: raise LoadError(f"Erro inesperado ao converter {src}: {e}.")
    csvs = list(tmp_dir.glob("*.csv"))
    if not csvs:
        base_csv = tmp_dir / f"{src.stem}.csv"
        if base_csv.exists(): csvs = [base_csv]
        else: raise LoadError(f"Nenhum CSV gerado para {src}.")
    return csvs

def load_to_df(path: Path, *, sep_default: str = ";") -> pd.DataFrame:
    ext = path.suffix.lower(); logger.info(f"Carregando '{path}' (ext: {ext}).")
    if ext == ".csv":
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                try: sep = csv.Sniffer().sniff(f.read(2048)).delimiter
                except csv.Error: sep = sep_default
            return pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False, encoding='utf-8-sig', low_memory=False)
        except Exception: return pd.read_csv(path, sep=sep_default, dtype=str, keep_default_na=False, encoding='utf-8-sig', low_memory=False)
    if ext == ".tsv": return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, encoding='utf-8-sig', low_memory=False)
    if ext in {".xlsx", ".xls", ".ods"}:
        try:
            excel_file = pd.ExcelFile(path)
            if not excel_file.sheet_names: raise LoadError(f"Nenhuma aba em {path}")
            dfs = [excel_file.parse(s, dtype=str, keep_default_na=False) for s in excel_file.sheet_names]
            if not dfs: raise LoadError(f"Nenhum DF carregado de {path}")
            return pd.concat(dfs, ignore_index=True)
        except Exception as e:
            logger.warning(f"Falha com pd.ExcelFile em '{path}' ({e}). Tentando LibreOffice.")
            csv_paths = _convert_xls_like_to_csvs(path)
            dfs = [pd.read_csv(p, sep=sep_default, dtype=str, keep_default_na=False, encoding='utf-8', low_memory=False) for p in csv_paths]
            if not dfs: raise LoadError(f"Nenhum DF carregado de {path} após conversão.")
            return pd.concat(dfs, ignore_index=True)
    raise LoadError(f"Extensão “{ext}” não suportada.")

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    seen, new_cols = {}, [];
    for col in df.columns:
        base = _norm(str(col)); idx = seen.get(base, 0); seen[base] = idx + 1
        new_cols.append(f"{base}_{idx}" if idx > 0 else base)
    df.columns = new_cols; return df

_PROMPT_COMPONENT_EXTRACTOR = textwrap.dedent("""\
Você é um assistente especialista em analisar pedidos de usuários sobre dados em planilhas e extrair os componentes da consulta.
Dada a pergunta do usuário e uma lista de nomes de colunas disponíveis na planilha, sua tarefa é retornar um objeto JSON com a seguinte estrutura:
{{
  "filters": [
    {{
      "column_user_suggestion": "Nome da coluna como o usuário mencionou ou você inferiu",
      "operator": "OPERADOR_LOGICO",
      "value": "Valor para o filtro"
    }}
  ],
  "sort_criteria": {{
    "column_user_suggestion": "Nome da coluna para ordenação",
    "direction": "ASC | DESC"
  }},
  "columns_to_display_user_suggestion": [
    "Nome da coluna 1 para exibir",
    "Nome da coluna 2 para exibir"
  ],
  "aggregation_request": {{
    "type": "SUM | COUNT | AVG | MIN | MAX | NONE",
    "column_user_suggestion": "Nome da coluna para agregar (ex: QTD, VALOR)"
  }}
}}

Considerações Importantes:
1.  **Colunas Disponíveis:** A seguir será fornecida uma lista de NOMES DE COLUNAS NORMALIZADOS. Ao preencher "column_user_suggestion", use o termo que o usuário usou ou um termo descritivo.
2.  **`filters`**:
    * Lista de objetos. Se nenhum filtro, retorne `[]`.
    * **`operator`**: Use `EQ`, `NOT`, `CONTAINS`, `GT`, `GTE`, `LT`, `LTE`.
    * **REGRA CRÍTICA PARA `CONTAINS` vs `EQ`:** Use `CONTAINS` quando o usuário buscar por uma palavra-chave ou descrever um estado (ex: "aguarda programação", "contém o termo 'importante'"). Use `EQ` apenas quando o usuário fornecer um valor que parece ser um identificador completo e exato (ex: "STATUS é 'Finalizado'").
    * **Exemplo de Estado:** Para "itens que aguardam programação" na coluna "SETOR", a saída correta é: `{{"column_user_suggestion": "SETOR", "operator": "CONTAINS", "value": "programação"}}`.
    * **Exemplo de Negação:** Para "desconsiderar itens com STATUS OK", a saída correta é: `{{"column_user_suggestion": "STATUS", "operator": "NOT", "value": "OK"}}`.
3.  **`sort_criteria`**: Se não houver ordenação, retorne `null`. "Prioridade de data de entrega" ou "mais antigo primeiro" implica `ASC`.
4.  **`columns_to_display_user_suggestion`**: Lista das colunas que o usuário pediu para ver. Se não especificou, retorne `[]`.
5.  **`aggregation_request`**: Para "Quantos produtos...", use `type: "SUM"` e `column_user_suggestion` para a coluna de quantidade (ex: "QTD"). Para "Conte os itens...", use `type: "COUNT"`. Se não houver agregação, use `type: "NONE"` ou retorne `null`.

Agora, analise o seguinte:
Colunas Disponíveis na Planilha (Normalizadas):
{actual_normalized_columns_str_list}

Pedido do Usuário:
\"\"\"{user_prompt}\"\"\"

Retorne APENAS o objeto JSON.
""")

def extract_query_components(user_prompt: str, actual_normalized_columns: list[str],
                             model_name: str = "gpt-4o-mini", max_retries: int = 1) -> dict:
    logger.info(f"Extraindo componentes da query para o prompt: '{user_prompt[:100]}...'")
    cols_str = ", ".join(f'"{col}"' for col in actual_normalized_columns)
    prompt_for_llm = _PROMPT_COMPONENT_EXTRACTOR.format(actual_normalized_columns_str_list=cols_str, user_prompt=user_prompt)
    is_gemini = "gemini" in model_name.lower(); messages = [{"role": "user", "content": prompt_for_llm}]
    default_err = {"error": "Falha ao extrair componentes.", "filters": [], "sort_criteria": None, "columns_to_display_user_suggestion": [], "aggregation_request": None}
    for attempt in range(max_retries + 1):
        try:
            raw_text = ""
            if is_gemini:
                gemini_history = [{'role': 'user', 'parts': [{'text': msg['content']}]} for msg in messages]
                raw_text, _ = chat_gemini(gemini_history, model=model_name, temperature=0.1)
            else:
                raw_text, _ = chat_openai(messages, model=model_name, temperature=0.1)
            logger.debug(f"Resposta crua do LLM (extração, tentativa {attempt + 1}): {raw_text}")
            json_candidate = _extract_json_candidate(raw_text)
            if not json_candidate: raise json.JSONDecodeError("JSON não encontrado.", raw_text, 0)
            parsed = json.loads(json_candidate)
            return {
                "filters": parsed.get("filters", []) if isinstance(parsed.get("filters"), list) else [],
                "sort_criteria": parsed.get("sort_criteria") if isinstance(parsed.get("sort_criteria"), dict) else None,
                "columns_to_display_user_suggestion": parsed.get("columns_to_display_user_suggestion", []) if isinstance(parsed.get("columns_to_display_user_suggestion"), list) else [],
                "aggregation_request": parsed.get("aggregation_request") if isinstance(parsed.get("aggregation_request"), dict) else None
            }
        except (json.JSONDecodeError, RuntimeError, Exception) as e:
            logger.warning(f"Erro na extração de componentes (tentativa {attempt + 1}): {type(e).__name__} - {e}")
            if attempt < max_retries:
                if not is_gemini: messages.extend([{"role": "assistant", "content": locals().get('raw_text', str(e))}, {"role": "user", "content": "A resposta anterior não foi um JSON válido. Tente novamente."}])
                time.sleep(0.7 * (attempt + 1))
            else: default_err["error"] = f"Falha final: {type(e).__name__} - {e}"; return default_err
    return default_err

def _map_user_column_to_normalized(
    user_col_suggestion: str | None, 
    actual_norm_cols: list[str], 
    orig_col_names: list[str] | None = None
) -> str | None:
    if not user_col_suggestion or not isinstance(user_col_suggestion, str): return None
    synonym_map = {
        _norm("QUANTIDADE A SER PRODUZIDA"): "QTD",_norm("QUANTIDADE"): "QTD",_norm("DATA DE ENTREGA"): "DATA_ENTREGA",
        _norm("DATA DE ENTREGA (PT-BR)"): "DATA_ENTREGA",_norm("REFERENCIA"): "REFERENCIA",_norm("DESCRICAO"): "DESCRICAO",}
    norm_sugg = _norm(user_col_suggestion)
    if norm_sugg in synonym_map and synonym_map[norm_sugg] in actual_norm_cols:
        logger.info(f"Coluna '{user_col_suggestion}' mapeada para '{synonym_map[norm_sugg]}' via sinônimo.")
        return synonym_map[norm_sugg]
    if norm_sugg in actual_norm_cols: return norm_sugg
    if orig_col_names and len(orig_col_names) == len(actual_norm_cols):
        for i, orig_col in enumerate(orig_col_names):
            if _norm(orig_col) == norm_sugg: return actual_norm_cols[i]
    search_space = actual_norm_cols + (orig_col_names or [])
    matches = difflib.get_close_matches(user_col_suggestion, search_space, n=1, cutoff=0.7)
    if matches:
        matched_name = matches[0]; logger.info(f"Mapeamento por aproximação: Sugestão '{user_col_suggestion}' correspondeu a '{matched_name}'.")
        if matched_name in actual_norm_cols: return matched_name
        if orig_col_names and matched_name in orig_col_names:
            try:
                idx = orig_col_names.index(matched_name)
                if idx < len(actual_norm_cols): return actual_norm_cols[idx]
            except (ValueError, IndexError): pass
    logger.warning(f"Não foi possível mapear a sugestão de coluna '{user_col_suggestion}' para nenhuma coluna disponível.")
    return None

def build_plan_from_components(
    components: dict, actual_norm_cols: list[str], orig_col_names: list[str] | None = None
) -> dict:
    plan = {"filter": "", "sort": "", "select_columns": [], "aggregation": None}
    if components.get("error"): logger.error(f"Erro na extração, construindo plano vazio: {components['error']}"); return plan
    
    valid_ops, filter_parts = _OPS.keys(), []
    for filt in components.get("filters", []):
        if not isinstance(filt, dict): continue
        user_col, op, val = filt.get("column_user_suggestion"), str(filt.get("operator", "")).upper(), filt.get("value")
        if user_col is None or val is None or not op: continue
        norm_col = _map_user_column_to_normalized(user_col, actual_norm_cols, orig_col_names)
        if norm_col and op in valid_ops: filter_parts.append(f"{norm_col}~{op}~{str(val)}")
        else: logger.warning(f"Filtro ignorado: Col='{user_col}', Op='{op}' (Válido? {op in valid_ops})")
    if filter_parts: plan["filter"] = ";".join(filter_parts)
    
    sort_crit = components.get("sort_criteria")
    if sort_crit and isinstance(sort_crit, dict):
        user_col, direction = sort_crit.get("column_user_suggestion"), str(sort_crit.get("direction", "ASC")).upper()
        if direction not in ["ASC", "DESC"]: direction = "ASC"
        if user_col:
            norm_col = _map_user_column_to_normalized(user_col, actual_norm_cols, orig_col_names)
            if norm_col: plan["sort"] = f"{norm_col}~{direction}"
            else: logger.warning(f"Coluna de ordenação '{user_col}' não mapeada.")
    
    user_select_cols = components.get("columns_to_display_user_suggestion", [])
    if isinstance(user_select_cols, list) and user_select_cols:
        selected_cols = [c for c in [_map_user_column_to_normalized(str(uc), actual_norm_cols, orig_col_names) for uc in user_select_cols] if c]
        if selected_cols: plan["select_columns"] = selected_cols
    
    agg_req = components.get("aggregation_request")
    if agg_req and isinstance(agg_req, dict):
        agg_type, user_col_agg = str(agg_req.get("type", "NONE")).upper(), agg_req.get("column_user_suggestion")
        if agg_type != "NONE" and agg_type in ["SUM", "COUNT", "AVG", "MIN", "MAX"]:
            norm_col_agg = _map_user_column_to_normalized(user_col_agg, actual_norm_cols, orig_col_names) if user_col_agg else None
            
            # REFINAMENTO DO PLANO PARA GROUPBY
            is_ranking_query = (agg_type in ["SUM", "COUNT"] and plan.get("select_columns") and len(plan["select_columns"]) == 1 and plan["select_columns"][0] != norm_col_agg)
            if is_ranking_query:
                plan["aggregation"] = {"type": f"GROUPBY_{agg_type}", "group_by_column": plan["select_columns"][0], "agg_column": norm_col_agg}
                plan["select_columns"] = [] # Limpa a seleção, pois o resultado será o ranking
                logger.info(f"Plano refinado para uma query de agrupamento: {plan['aggregation']}")


def build_plan_from_components(
    components: dict, 
    actual_norm_cols: list[str], 
    orig_col_names: list[str] | None = None
) -> dict:
    """
    Constrói o dicionário de plano final (para run_plan) a partir dos componentes 
    extraídos pelo LLM, aplicando lógica determinística e validações.
    """
    plan = {"filter": "", "sort": "", "select_columns": [], "aggregation": None}
    
    if components.get("error"):
        logger.error(f"Erro na extração de componentes, construindo plano vazio: {components['error']}")
        return plan

    # 1. Processar Filtros
    valid_ops, filter_parts = _OPS.keys(), []
    for filt in components.get("filters", []):
        if not isinstance(filt, dict): continue
        user_col, op, val = filt.get("column_user_suggestion"), str(filt.get("operator", "")).upper(), filt.get("value")
        if user_col is None or val is None or not op: continue
        
        norm_col = _map_user_column_to_normalized(user_col, actual_norm_cols, orig_col_names)
        if norm_col and op in valid_ops:
            filter_parts.append(f"{norm_col}~{op}~{str(val)}")
        else:
            logger.warning(f"Filtro ignorado: Col='{user_col}', Op='{op}' (Válido? {op in valid_ops})")
    
    if filter_parts:
        plan["filter"] = ";".join(filter_parts)

    # 2. Processar Ordenação
    sort_crit = components.get("sort_criteria")
    if sort_crit and isinstance(sort_crit, dict):
        user_col, direction = sort_crit.get("column_user_suggestion"), str(sort_crit.get("direction", "ASC")).upper()
        if direction not in ["ASC", "DESC"]: direction = "ASC"
        if user_col:
            norm_col = _map_user_column_to_normalized(user_col, actual_norm_cols, orig_col_names)
            if norm_col:
                plan["sort"] = f"{norm_col}~{direction}"
            else:
                logger.warning(f"Coluna de ordenação '{user_col}' não mapeada.")
    
    # 3. Processar Colunas de Seleção
    user_select_cols = components.get("columns_to_display_user_suggestion", [])
    if isinstance(user_select_cols, list) and user_select_cols:
        # Mapeia cada coluna sugerida para seu nome normalizado real
        selected_cols = [
            norm_col for uc in user_select_cols 
            if (norm_col := _map_user_column_to_normalized(str(uc), actual_norm_cols, orig_col_names)) is not None
        ]
        if selected_cols:
            plan["select_columns"] = selected_cols
    
    # 4. Processar Agregação e Refinar o Plano (Lógica de GROUPBY)
    agg_req = components.get("aggregation_request")
    if agg_req and isinstance(agg_req, dict):
        agg_type = str(agg_req.get("type", "NONE")).upper()
        user_col_agg = agg_req.get("column_user_suggestion")
        
        if agg_type != "NONE" and agg_type in ["SUM", "COUNT", "AVG", "MIN", "MAX", "FIRST"]:
            norm_col_agg = _map_user_column_to_normalized(user_col_agg, actual_norm_cols, orig_col_names) if user_col_agg else None
            
            # Heurística de Refinamento: Detecta um pedido de ranking/agrupamento
            is_ranking_query = (
                agg_type in ["SUM", "COUNT"] and
                plan.get("select_columns") and
                len(plan["select_columns"]) == 1 and
                plan["select_columns"][0] != norm_col_agg
            )

            if is_ranking_query:
                # Transforma em um novo tipo de agregação customizada
                plan["aggregation"] = {
                    "type": f"GROUPBY_{agg_type}", # Ex: GROUPBY_SUM ou GROUPBY_COUNT
                    "group_by_column": plan["select_columns"][0], # A coluna a ser agrupada
                    "agg_column": norm_col_agg # A coluna a ser somada/contada
                }
                plan["select_columns"] = [] # Limpa a seleção de colunas, pois o resultado será o ranking
                logger.info(f"Plano refinado para uma query de agrupamento: {plan['aggregation']}")
            
            # Lógica para agregação simples
            elif agg_type in ["SUM", "AVG", "MIN", "MAX"] and not norm_col_agg: 
                logger.warning(f"Agregação '{agg_type}' requer coluna válida, mas '{user_col_agg}' não mapeou. Ignorando.")
            else:
                plan["aggregation"] = {"type": agg_type, "column": norm_col_agg}
        elif agg_type != "NONE": 
            logger.warning(f"Tipo de agregação inválido '{agg_type}' ignorado.")

    logger.info(f"Plano final construído: {plan}")
    return plan

_OPS = {
    "EQ": lambda s, v: s.astype(str).str.lower() == str(v).lower(), "NOT": lambda s, v: s.astype(str).str.lower() != str(v).lower(),
    "CONTAINS": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False, regex=False),
    "GT": lambda s, v: pd.to_numeric(s, errors='coerce') > pd.to_numeric(v, errors='coerce'), "GTE": lambda s, v: pd.to_numeric(s, errors='coerce') >= pd.to_numeric(v, errors='coerce'),
    "LT": lambda s, v: pd.to_numeric(s, errors='coerce') < pd.to_numeric(v, errors='coerce'), "LTE": lambda s, v: pd.to_numeric(s, errors='coerce') <= pd.to_numeric(v, errors='coerce'),
}

def _apply_single(df: pd.DataFrame, expr: str) -> pd.DataFrame:
    try: col, op, val_str = expr.split("~", 2); col, op = col.strip(), op.strip().upper()
    except ValueError: raise ValueError(f"Filtro malformado: {expr!r}")
    if op not in _OPS: raise ValueError(f"Operador não suportado: {op}")
    if col not in df.columns: raise ValueError(f"Coluna de filtro inexistente: {col}")
    try: return df[_OPS[op](df[col], val_str)]
    except Exception as e: raise ValueError(f"Erro ao aplicar filtro '{expr}': {e}") from e

def run_plan(df: pd.DataFrame, plan: dict) -> pd.DataFrame | Any:
    temp_df = df.copy()

    if plan.get("filter"):
        for expr in [p.strip() for p in plan["filter"].split(";") if p.strip()]:
            try: temp_df = _apply_single(temp_df, expr)
            except ValueError as e: logger.warning(f"Ignorando filtro inválido '{expr}': {e}")
    
    if plan.get("sort") and not temp_df.empty:
        try:
            col, direction = plan["sort"].split("~", 1); asc = direction.strip().upper() != "DESC"
            if col in temp_df.columns:
                if ('DATA' in col.upper() or 'DATE' in col.upper()) and not pd.api.types.is_datetime64_any_dtype(temp_df[col]):
                    temp_sort_col = "__temp_sort_col__"
                    temp_df[temp_sort_col] = pd.to_datetime(temp_df[col], errors='coerce', dayfirst=True)
                    temp_df.sort_values(by=temp_sort_col, ascending=asc, na_position='last', inplace=True)
                    temp_df.drop(columns=[temp_sort_col], inplace=True)
                else:
                    temp_df.sort_values(by=col, ascending=asc, kind='mergesort', na_position='last', inplace=True)
            else: logger.warning(f"Coluna de ordenação '{col}' não encontrada.")
        except Exception as e: logger.error(f"Erro na ordenação por '{plan['sort']}': {e}", exc_info=True)
    
    agg = plan.get("aggregation")
    if agg and isinstance(agg, dict) and agg.get("type") != "NONE":
        agg_type = agg.get("type")
        
        if "GROUPBY" in agg_type:
            group_by_col = agg.get("group_by_column")
            agg_col = agg.get("agg_column")
            if temp_df.empty: return pd.DataFrame()
            if group_by_col and group_by_col in temp_df.columns:
                grouped_data = None
                if agg_type == "GROUPBY_SUM" and agg_col and agg_col in temp_df.columns:
                    grouped_data = temp_df.groupby(group_by_col).agg(total=(agg_col, lambda x: pd.to_numeric(x, errors='coerce').sum())).sort_values(by='total', ascending=False)
                elif agg_type == "GROUPBY_COUNT":
                    grouped_data = temp_df.groupby(group_by_col).size().reset_index(name='contagem').sort_values(by='contagem', ascending=False)
                if grouped_data is not None: return grouped_data.reset_index()
            logger.warning(f"Não foi possível executar a agregação de agrupamento: {agg}")
        else:
            agg_col = agg.get("column")
            if temp_df.empty and agg_type != "COUNT": return 0 if agg_type == "SUM" else None
            if agg_type == "COUNT": return temp_df[agg_col].count() if agg_col and agg_col in temp_df.columns else len(temp_df)
            if agg_col and agg_col in temp_df.columns:
                series = pd.to_numeric(temp_df[agg_col], errors='coerce')
                if agg_type == "SUM": return series.sum()
                if agg_type == "AVG": return series.mean()
                if agg_type == "MIN": return series.min()
                if agg_type == "MAX": return series.max()
            logger.warning(f"Agregação simples '{agg_type}' na coluna '{agg_col}' não pôde ser realizada.")
    
    select_cols = plan.get("select_columns", [])
    if isinstance(select_cols, list) and select_cols:
        valid_cols = [c for c in select_cols if c in temp_df.columns]
        if valid_cols:
            if len(valid_cols) < len(select_cols): logger.warning(f"Colunas não encontradas e ignoradas: {set(select_cols) - set(valid_cols)}")
            temp_df = temp_df[valid_cols]
        else: logger.warning(f"Nenhuma das colunas solicitadas para seleção {select_cols} existe.")
    
    return temp_df.reset_index(drop=True)

__all__ = ["chat_openai", "chat_gemini", "load_to_df", "normalize_columns", "_norm", "LoadError", "extract_query_components", "build_plan_from_components", "run_plan"]