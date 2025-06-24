"""
Utilitários genéricos para conversão, leitura e compactação de planilhas.
Nada aqui depende de nomes de colunas específicos: tudo é detectado
dinamicamente em tempo-real.

• Converte qualquer .xlsx/.xls/.ods em CSV via LibreOffice
• Lê todos os CSVs em um único DataFrame pandas
• Normaliza cabeçalhos (remove acentos, espaços, duplica se necessário)
• Extrai regras de filtragem do prompt do usuário
• Aplica filtros localmente (mais rápido e barato que pedir ao LLM)
• Gera bloco compacto (<META><HEADER><DATA>) que cabe no contexto do modelo
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import List, Tuple

import pandas as pd

# --------------------------------------------------------------------------- #
#  Configurações (podem ser sobre-escritas em settings com os.getenv)         #
# --------------------------------------------------------------------------- #
SOFFICE_BIN = os.getenv("SOFFICE_PATH", "/usr/bin/soffice")
CSV_FILTER  = "csv:Text - txt - csv (StarCalc):59,34,0,1"   # ;  "  UTF-8

MAX_SAMPLE_LINES_MODEL = int(os.getenv("IA_SPREADSHEET_MAX_ROWS_TO_MODEL", 200))

# Utilizado apenas quando precisamos quebrar uma planilha muito grande
_MAX_SAMPLE_LINES_FALLBACK = 1_000
_MAX_SAMPLE_KB_FALLBACK    = 40

# --------------------------------------------------------------------------- #
#  Exceção customizada                                                        #
# --------------------------------------------------------------------------- #
class SpreadsheetExtractionError(RuntimeError):
    ...

# --------------------------------------------------------------------------- #
#  1)  Converte a planilha para CSV (um CSV por aba)                          #
# --------------------------------------------------------------------------- #
def convert_to_csv(src_path: Path) -> List[Path]:
    """
    Recebe Path de .xlsx/.xls/.ods/.csv/.tsv e devolve
    uma lista de CSVs recém-gerados em /tmp. Se o arquivo
    já for CSV/TSV, devolve lista com ele mesmo.
    """
    suffix = src_path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return [src_path]

    if not Path(SOFFICE_BIN).exists():
        raise SpreadsheetExtractionError("LibreOffice (soffice) não encontrado.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="ia_csv_"))
    cmd = [
        SOFFICE_BIN,
        "--headless",
        "--convert-to", CSV_FILTER,
        "--outdir",      str(tmp_dir),
        str(src_path),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        raise SpreadsheetExtractionError(
            f"Falha LibreOffice: {res.stderr.decode()[:400]}"
        )

    csvs = list(tmp_dir.glob("*.csv"))
    if not csvs:
        raise SpreadsheetExtractionError("Nenhum CSV gerado pela conversão.")
    return csvs

# --------------------------------------------------------------------------- #
#  2)  Carrega CSVs → pandas DataFrame                                        #
# --------------------------------------------------------------------------- #
def load_dataframe(csv_paths: list[Path], delimiter: str = ";") -> pd.DataFrame:
    """Concatena todas as abas (CSVs) em um único DataFrame."""
    frames = [
        pd.read_csv(p, sep=delimiter, dtype=str, keep_default_na=False)
        for p in csv_paths
    ]
    return pd.concat(frames, ignore_index=True)

# --------------------------------------------------------------------------- #
#  3)  Normalização de cabeçalhos                                             #
# --------------------------------------------------------------------------- #
def _normalize(col: str) -> str:
    txt = unicodedata.normalize("NFKD", col)
    txt = txt.encode("ascii", "ignore").decode()
    txt = re.sub(r"\W+", "_", txt).strip("_").upper()
    return txt or "COL"

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove acentos/espaços e garante unicidade das colunas."""
    new_cols, seen = [], {}
    for c in df.columns:
        base = _normalize(c)
        idx  = seen.get(base, 0)
        seen[base] = idx + 1
        new_cols.append(f"{base}_{idx}" if idx else base)
    df.columns = new_cols
    return df

# --------------------------------------------------------------------------- #
#  4)  Extrai filtros do prompt (regex simples, porém funciona bem)           #
# --------------------------------------------------------------------------- #
EQ_PAT      = re.compile(r'COLUNA\s+"?([\w\s]+?)"?\s+.*?\s+IGUAL\s+A\s+"?([\w\s]+?)"', re.I)
NEQ_PAT     = re.compile(r'COLUNA\s+"?([\w\s]+?)"?\s+.*?\s+DIFERENTE\s+DE\s+"?([\w\s]+?)"', re.I)
CONTAINS_PAT= re.compile(r'COLUNA\s+"?([\w\s]+?)"?[^"]+CONT[ÉE]M\s+"?([\w\s]+?)"', re.I)

def parse_filters_from_prompt(prompt: str) -> list[tuple[str,str,str]]:
    """
    Retorna lista de filtros (COLUNA_NORMALIZADA, operador, valor)
    operador ∈ {'eq','neq','contains'}
    """
    out: list[tuple[str,str,str]] = []
    for col,val in EQ_PAT.findall(prompt):
        out.append((_normalize(col), "eq", val))
    for col,val in NEQ_PAT.findall(prompt):
        out.append((_normalize(col), "neq", val))
    for col,val in CONTAINS_PAT.findall(prompt):
        out.append((_normalize(col), "contains", val))
    return out

# --------------------------------------------------------------------------- #
#  5)  Aplica filtros no DataFrame                                            #
# --------------------------------------------------------------------------- #
def apply_filters(df: pd.DataFrame, filters: list[tuple[str,str,str]]) -> pd.DataFrame:
    for col, op, val in filters:
        if col not in df.columns:
            continue                        # ignora coluna inexistente
        if op == "eq":
            df = df[df[col].str.fullmatch(val, case=False, na=False)]
        elif op == "neq":
            df = df[~df[col].str.fullmatch(val, case=False, na=False)]
        elif op == "contains":
            df = df[df[col].str.contains(val, case=False, na=False)]
    return df

# --------------------------------------------------------------------------- #
#  6)  Compacta resultado para caber no contexto do LLM                       #
# --------------------------------------------------------------------------- #
def df_to_prompt_block(df: pd.DataFrame, filename: str) -> str:
    rows = len(df)
    if rows == 0:
        return f"<DATA>\n(Nenhuma linha restante após filtro em {filename})"

    if rows > MAX_SAMPLE_LINES_MODEL:
        head = df.head(MAX_SAMPLE_LINES_MODEL // 2)
        tail = df.tail(MAX_SAMPLE_LINES_MODEL // 2)
        df_small = pd.concat([head, tail])
        note = f"\n# OBS.: {rows - len(df_small)} linhas omitidas para reduzir contexto."
    else:
        df_small = df
        note = ""

    csv_txt = df_small.to_csv(sep=";", index=False, line_terminator="\n")
    header  = ";".join(df_small.columns)

    meta = [
        "<META>",
        f"Arquivo_original = \"{filename}\"",
        f"Linhas_totais    = {rows}",
        f"Colunas_totais   = {len(df.columns)}",
        "",
        "<HEADER>",
        header,
        "",
    ]

    return "\n".join(meta) + "<DATA>\n" + csv_txt + note
