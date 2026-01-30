"""
Streamlit app - Tangerino Punch Sync (diagnóstico aprimorado)

Objetivos:
- Ler token de `st.secrets["TANGERINO_TOKEN"]` ou variável de ambiente TANGERINO_TOKEN.
- Permitir escolher endpoint (punch, punch/search, punch/page, v1/...).
- Fornecer filtros (lastUpdate, startDate, endDate, employeeId, status) com defaults.
- Fazer chamadas paginadas e exibir: status code, response headers, raw body (texto), parsed JSON preview,
  e campos de paginação (first/last/number/totalPages/totalElements).
- Logar respostas completas em arquivo (logs/api_responses.log) e mostrar últimas linhas no UI.
- Salvar resultados em SQLite (punches.db) e permitir exportar CSV completo.
- Modo DEBUG que mostra request URL completo, params e headers (evite habilitar em produção).

Como usar:
1. Configure o secret no Streamlit Cloud: TANGERINO_TOKEN = "Basic ...".
2. Local: export TANGERINO_TOKEN="Basic ..." ou cole no campo token manual se desejar.
3. Ajuste Base URL / endpoint e filtros, clique em Sync.
"""

import os
import json
import time
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import requests
import pandas as pd

# ---------------------------
# CONFIG / CONSTANTS
# ---------------------------
DEFAULT_BASE = "https://api.tangerino.com.br/api"
DEFAULT_ENDPOINTS = [
    "/punch/v2",
    "/punch/search",
    "/punch/page",
    "/v1/punch",
    "/v1/punch/search",
]
DB_PATH = "punches.db"
LOG_PATH = "logs/api_responses.log"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Setup logging (app-level)
logger = logging.getLogger("tangerino_debug")
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(file_handler)

# ---------------------------
# DB HELPERS
# ---------------------------
def get_conn(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    init_db(conn)
    return conn

def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS punches (
        id INTEGER PRIMARY KEY,
        employeeId INTEGER,
        date TEXT,
        status TEXT,
        lastModifiedDate TEXT,
        raw_json TEXT,
        saved_at INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    conn.commit()

def set_metadata(conn: sqlite3.Connection, key: str, value: str):
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

def get_metadata(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("SELECT value FROM metadata WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row else None

def save_punches(conn: sqlite3.Connection, punches: List[Dict[str, Any]]) -> int:
    cur = conn.cursor()
    now_ms = int(time.time() * 1000)
    saved = 0
    for p in punches:
        try:
            pid = p.get("id")
            emp = p.get("employeeId") or (p.get("employee") or {}).get("id")
            date = p.get("date")
            status = p.get("status")
            last_mod = p.get("lastModifiedDate")
            raw = json.dumps(p, ensure_ascii=False)
            cur.execute("""
                INSERT OR REPLACE INTO punches (id, employeeId, date, status, lastModifiedDate, raw_json, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pid, emp, date, status, last_mod, raw, now_ms))
            saved += 1
        except Exception as e:
            logger.exception("Erro salvando punch id %s: %s", p.get("id"), e)
    conn.commit()
    return saved

# ---------------------------
# API FETCH + DEBUGGING
# ---------------------------
def pretty_json(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

def log_response_details(req_info: Dict[str, Any], status_code: Optional[int], headers: Dict[str, Any], text: str):
    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "request": req_info,
        "status_code": status_code,
        "response_headers": dict(headers) if headers else {},
        "response_text_truncated": text[:2000]  # avoid giant logs; full text in UI if needed
    }
    logger.debug(json.dumps(payload, ensure_ascii=False))

def fetch_punches(
    base_url: str,
    endpoint: str,
    token: str,
    params: Dict[str, Any],
    page_size: int = 200,
    max_pages: int = 1000,
    debug: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Faz requisições paginadas ao endpoint e retorna (all_punches, last_response_meta)
    last_response_meta contém status code, last raw text, last parsed json (if any), and pagination fields.
    """
    headers = {
        "Authorization": token,
        "Accept": "application/json"
    }

    all_punches: List[Dict[str, Any]] = []
    page = 0
    last_meta: Dict[str, Any] = {}

    # Ensure page/size appear in params
    params = params.copy()
    params.setdefault("size", page_size)

    base_endpoint = base_url.rstrip("/") + endpoint

    while True:
        params["page"] = page
        req_info = {"url": base_endpoint, "params": params, "headers_keys": list(headers.keys())}
        if debug:
            logger.debug("Requesting: %s ? %s", base_endpoint, params)

        try:
            resp = requests.get(base_endpoint, headers=headers, params=params, timeout=30)
        except Exception as e:
            # network-level error
            logger.exception("Network error calling API: %s", e)
            last_meta = {"error": "network_error", "exception": str(e)}
            return all_punches, last_meta

        status = resp.status_code
        text = resp.text

        # Log an abbreviated version to file
        log_response_details(req_info, status, resp.headers, text)

        # Build last_meta for UI
        last_meta = {
            "url": resp.url,
            "status_code": status,
            "headers": dict(resp.headers),
            "text": text[:10000]  # keep reasonable length in-memory
        }

        # Display full debug info in the UI (handled by caller)
        if not resp.ok:
            # Try to parse JSON error body (if any)
            try:
                json_body = resp.json()
                last_meta["json"] = json_body
            except Exception:
                last_meta["json"] = None

            # Return early so the UI can show details and we don't silently raise
            return all_punches, last_meta

        # If OK: try parse as JSON and extract content
        try:
            data = resp.json()
        except Exception as e:
            # JSON parse error — surface for debugging
            last_meta["json_parse_error"] = str(e)
            last_meta["text_full"] = text
            return all_punches, last_meta

        # Append content if present
        content = data.get("content")
        if isinstance(content, list):
            all_punches.extend(content)
        else:
            # If API uses different shape (maybe returns list directly)
            if isinstance(data, list):
                all_punches.extend(data)
            elif content is None:
                # no 'content' key: possibly single page with other schema; try to find list keys
                # try 'items' or 'data'
                for candidate in ("items", "data", "result"):
                    if candidate in data and isinstance(data[candidate], list):
                        all_punches.extend(data[candidate])
                        break

        # update last_meta with pagination info (if present)
        for k in ("first", "last", "number", "totalPages", "numberOfElements", "totalElements", "size"):
            if k in data:
                last_meta[k] = data.get(k)

        # If response signals last page, break
        if data.get("last") is True:
            last_meta["finished_reason"] = "last_flag_true"
            break

        # If returned no items, break (safety)
        if isinstance(content, list) and len(content) == 0:
            last_meta["finished_reason"] = "empty_content"
            break

        page += 1
        if page >= max_pages:
            last_meta["finished_reason"] = "max_pages_reached"
            break

    return all_punches, last_meta

# ---------------------------
# STREAMLIT UI
# ---------------------------

st.set_page_config(page_title="Tangerino Debug Sync", layout="wide")
st.title("Tangerino — Sync & Debug (diagnóstico)")

# --- Secrets / Token handling
token_from_secrets = None
try:
    token_from_secrets = st.secrets.get("TANGERINO_TOKEN")  # works on Streamlit Cloud
except Exception:
    token_from_secrets = None

token_env = os.getenv("TANGERINO_TOKEN")
token_input = None

st.sidebar.header("Configuração")
base_url = st.sidebar.text_input("Base URL (host)", value=DEFAULT_BASE)
endpoint = st.sidebar.selectbox("Endpoint (escolha para testar)", options=DEFAULT_ENDPOINTS, index=1)
page_size = st.sidebar.number_input("page size (size)", min_value=10, max_value=1000, value=200, step=10)
max_pages = st.sidebar.number_input("max pages (safety)", min_value=1, max_value=5000, value=500, step=50)
debug_mode = st.sidebar.checkbox("DEBUG mode (mostrar request/headers)", value=True)

if token_from_secrets:
    st.sidebar.success("Token carregado de st.secrets")
    token = token_from_secrets
else:
    if token_env:
        st.sidebar.info("Token encontrado em VAR DE AMBIENTE (TANGERINO_TOKEN)")
    token_input = st.sidebar.text_area("Token (se não usar secrets/ENV cole aqui)", value=token_env or "", height=80)
    token = token_input.strip()

if not token:
    st.error("Token não encontrado. Configure st.secrets['TANGERINO_TOKEN'] no Streamlit Cloud ou exporte TANGERINO_TOKEN localmente ou cole o token aqui.")
    st.stop()

# --- Filters / Defaults
st.sidebar.markdown("### Filtros (padrões sugeridos para diagnóstico)")
# default lastUpdate: 12 months ago in ms
default_last_ms = int((time.time() - 60 * 60 * 24 * 365) * 1000)
units = st.sidebar.selectbox("Unidade lastUpdate", options=["milliseconds", "seconds"], index=0)
last_update_input = st.sidebar.text_input("lastUpdate integer (0 para tudo)", value=str(default_last_ms))
start_date = st.sidebar.text_input("startDate (YYYY-MM-DD) - opcional", value="")
end_date = st.sidebar.text_input("endDate (YYYY-MM-DD) - opcional", value="")
employee_id = st.sidebar.text_input("employeeId (opcional)", value="")
status_filter = st.sidebar.selectbox("status (opcional)", options=["", "APPROVED", "PENDING", "REPROVED"], index=0)
only_pending = st.sidebar.checkbox("onlyPending (true/false)", value=False)
show_raw_response = st.sidebar.checkbox("Mostrar RAW completo da última resposta", value=False)

# Convert lastUpdate to integer according to units
try:
    last_update_val = int(last_update_input)
    if units == "seconds":
        last_update_param = last_update_val
    else:
        last_update_param = last_update_val
except Exception:
    st.sidebar.error("lastUpdate deve ser um inteiro. Usando default (12 meses atrás).")
    last_update_param = default_last_ms

# Build base params dict for calls
params_base: Dict[str, Any] = {"lastUpdate": last_update_param}
if start_date:
    params_base["startDate"] = start_date
if end_date:
    params_base["endDate"] = end_date
if employee_id:
    try:
        params_base["employeeId"] = int(employee_id)
    except Exception:
        params_base["employeeId"] = employee_id
if status_filter:
    params_base["status"] = status_filter
if only_pending:
    params_base["onlyPending"] = "true"  # API expects strings like 'true' sometimes

# Controls
st.sidebar.markdown("---")
st.sidebar.markdown("⚠️ Em caso de erro, verifique o campo 'HTTP / RAW' e os logs (aba 'Logs').")

# Main actions
conn = get_conn(DB_PATH)

col1, col2, col3 = st.columns([1,1,1])
with col1:
    sync_incremental = st.button("🔄 Sync incremental (lastUpdate salvo)")
with col2:
    sync_full = st.button("📥 Force full sync (lastUpdate=0)")
with col3:
    export_csv = st.button("⬇️ Exportar CSV completo")

# Last saved sync info
raw_last = get_metadata(conn, "last_sync")
if raw_last:
    try:
        last_iso = datetime.fromtimestamp(int(raw_last)/1000, tz=timezone.utc).astimezone().isoformat()
    except Exception:
        last_iso = raw_last
    st.info(f"Último sync salvo: {last_iso}")
else:
    st.info("Nenhum sync anterior encontrado.")

# Placeholders for UI outputs
status_placeholder = st.empty()
debug_expander = st.expander("Diagnóstico e resposta HTTP (detalhes)", expanded=True)
with debug_expander:
    http_info = st.container()
    raw_container = st.container()
    parse_container = st.container()

# Logs viewer
with st.expander("Logs (últimas linhas)", expanded=False):
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-400:]  # mostra até últimas 400 linhas
            st.code("".join(lines[-200:]) or "Sem logs ainda.")
    except FileNotFoundError:
        st.write("Arquivo de log não encontrado (ainda não houve chamadas).")

# Helper to run fetch and show debug info
def perform_fetch(use_full: bool):
    # compute params
    if use_full:
        params = params_base.copy()
        params["lastUpdate"] = 0
    else:
        params = params_base.copy()
    params["size"] = page_size

    # call fetcher
    endpoint_path = endpoint  # selected by user
    all_punches, meta = fetch_punches(base_url, endpoint_path, token, params, page_size=page_size, max_pages=max_pages, debug=debug_mode)

    # show summary
    status_placeholder.info(f"Chamadas finalizadas. Registros retornados nesta execução: {len(all_punches)}")

    # Show HTTP / RAW details
    with http_info:
        st.subheader("HTTP / RAW")
        if meta.get("status_code") is None and meta.get("error"):
            st.error(f"Erro de rede: {meta.get('error')}")
            st.write(meta.get("exception", ""))
        else:
            st.write("URL chamada:", meta.get("url"))
            st.write("Status code:", meta.get("status_code"))
            st.write("Response headers (parciais):")
            # show some headers
            headers_preview = {k:v for k,v in list(meta.get("headers", {}).items())[:10]}
            st.json(headers_preview)
            # full raw text if requested
            if show_raw_response:
                st.subheader("Response text (até 10000 chars shown)")
                st.text(meta.get("text", "")[:10000])
            # show parsed JSON if present
            if meta.get("json"):
                st.subheader("Response JSON (parcial)")
                st.json(meta.get("json"))

            # show pagination/meta fields detected
            pagination_keys = {k: meta[k] for k in ("first","last","number","totalPages","numberOfElements","totalElements","size") if k in meta}
            if pagination_keys:
                st.write("Campos de paginação detectados:")
                st.json(pagination_keys)

    # Show parse info
    with parse_container:
        st.subheader("Parse / Conteúdo")
        if len(all_punches) == 0:
            st.info("Nenhum item/registro retornado na resposta (lista vazia).")
        else:
            # show table preview
            rows = []
            for p in all_punches[:200]:
                rows.append({
                    "id": p.get("id"),
                    "employeeId": p.get("employeeId") or (p.get("employee") or {}).get("id"),
                    "employeeName": p.get("employeeName") or (p.get("employee") or {}).get("name"),
                    "date": p.get("date"),
                    "status": p.get("status")
                })
            df_preview = pd.DataFrame(rows)
            st.dataframe(df_preview)

    # Save to DB if any
    if all_punches:
        saved_count = save_punches(conn, all_punches)
        set_metadata(conn, "last_sync", str(int(time.time() * 1000)))
        st.success(f"{saved_count} registros salvos no DB local.")

    # Always return meta for potential additional actions
    return all_punches, meta

# Execute actions
if sync_incremental:
    st.info("Executando sync incremental com parâmetros atuais...")
    perform_fetch(use_full=False)

if sync_full:
    st.info("Executando sync completo (lastUpdate=0)...")
    perform_fetch(use_full=True)

if export_csv:
    df_all = pd.read_sql_query("SELECT * FROM punches ORDER BY saved_at DESC", conn)
    csv = df_all.to_csv(index=False)
    st.download_button("Download CSV completo", data=csv, file_name="tangerino_punches_full.csv", mime="text/csv")

# Footer: preview last 50
st.markdown("---")
st.subheader("Preview — últimos 50 registros salvos no DB")
df_preview_db = pd.read_sql_query("SELECT id, employeeId, date, status, lastModifiedDate FROM punches ORDER BY saved_at DESC LIMIT 50", conn)
st.dataframe(df_preview_db)
