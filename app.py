import os
import time
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import streamlit as st
import requests
import pandas as pd

# =====================================================
# CONFIG
# =====================================================

DEFAULT_BASE_URL = "https://apis.tangerino.com.br/punch"
DB_PATH = "punches.db"

# =====================================================
# UTILS
# =====================================================

def now_ms():
    return int(time.time() * 1000)

def days_ago_ms(days):
    return int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().isoformat()

# =====================================================
# DATABASE
# =====================================================

def init_db(conn):
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

def get_meta(conn, key):
    cur = conn.cursor()
    cur.execute("SELECT value FROM metadata WHERE key=?", (key,))
    r = cur.fetchone()
    return r[0] if r else None

def set_meta(conn, key, value):
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, value))
    conn.commit()

def save_punches(conn, items):
    cur = conn.cursor()
    ts = now_ms()
    count = 0

    for p in items:
        cur.execute("""
        INSERT OR REPLACE INTO punches
        (id, employeeId, date, status, lastModifiedDate, raw_json, saved_at)
        VALUES (?,?,?,?,?,?,?)
        """, (
            p.get("id"),
            p.get("employeeId") or (p.get("employee") or {}).get("id"),
            p.get("date"),
            p.get("status"),
            p.get("lastModifiedDate"),
            json.dumps(p, ensure_ascii=False),
            ts
        ))
        count += 1

    conn.commit()
    return count

# =====================================================
# API CALL
# =====================================================

def fetch_page(base_url, token, params):
    headers = {
        "Authorization": token,
        "Accept": "application/json"
    }

    r = requests.get(base_url, headers=headers, params=params, timeout=40)

    st.code(f"URL chamada:\n{r.url}")

    if not r.ok:
        st.error(f"HTTP {r.status_code}")
        st.json(r.headers)
        try:
            st.json(r.json())
        except:
            st.text(r.text)
        raise Exception("Erro na API")

    return r.json()

def fetch_all(base_url, token, base_params):
    page = 0
    all_items = []

    while True:
        params = base_params.copy()
        params["page"] = page
        params["size"] = base_params.get("size", 200)

        data = fetch_page(base_url, token, params)

        content = data.get("content") or data.get("items") or data.get("data")

        if not content:
            break

        all_items.extend(content)

        is_last = data.get("last")
        total_pages = data.get("totalPages")

        if is_last is True:
            break
        if total_pages and page + 1 >= total_pages:
            break

        page += 1

    return all_items

# =====================================================
# STREAMLIT UI
# =====================================================

st.set_page_config("Tangerino Punch Sync", layout="wide")
st.title("📊 Tangerino – Ingestão profissional de Punches")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
init_db(conn)

# =====================================================
# TOKEN
# =====================================================

token = st.secrets.get("TANGERINO_TOKEN") or os.getenv("TANGERINO_TOKEN")

if not token:
    st.error("Configure TANGERINO_TOKEN nos Secrets do Streamlit ou variável de ambiente")
    st.stop()

# =====================================================
# SIDEBAR – FILTROS
# =====================================================

with st.sidebar:
    st.header("🔧 Configuração API")

    base_url = st.text_input("Endpoint", DEFAULT_BASE_URL)

    st.markdown("### 📅 Período (para carga completa)")

    default_start = datetime.now().date() - timedelta(days=90)
    default_end = datetime.now().date()

    start_date = st.date_input("Data inicial", default_start)
    end_date = st.date_input("Data final", default_end)

    start_ms = int(datetime.combine(start_date, datetime.min.time()).timestamp() * 1000)
    end_ms = int(datetime.combine(end_date, datetime.max.time()).timestamp() * 1000)

    st.markdown("### ⚙️ Parâmetros")

    page_size = st.number_input("Page size", 50, 1000, 200, 50)

    status = st.selectbox("Status", ["", "APPROVED", "PENDING", "REPROVED"])

    employee_id = st.text_input("Employee ID (opcional)")

# =====================================================
# LAST SYNC
# =====================================================

last_sync = get_meta(conn, "last_sync")

if last_sync:
    st.info(f"Último sync incremental: {ms_to_iso(int(last_sync))}")
else:
    st.info("Nenhum sync incremental executado ainda")

# =====================================================
# ACTIONS
# =====================================================

col1, col2, col3 = st.columns(3)

# ---------- FULL LOAD ----------
with col1:
    if st.button("📥 Carga completa por período"):
        params = {
            "startDate": start_ms,
            "endDate": end_ms,
            "size": page_size
        }

        if status:
            params["status"] = status

        if employee_id:
            params["employeeId"] = employee_id

        st.write("Parâmetros usados:")
        st.json(params)

        data = fetch_all(base_url, token, params)
        saved = save_punches(conn, data)

        set_meta(conn, "last_sync", str(now_ms()))

        st.success(f"{saved} registros importados.")

# ---------- INCREMENTAL ----------
with col2:
    if st.button("🔄 Sync incremental (lastUpdate)"):
        if not last_sync:
            st.warning("Nenhum last_sync encontrado — execute uma carga completa primeiro")
            st.stop()

        params = {
            "lastUpdate": int(last_sync),
            "size": page_size
        }

        if status:
            params["status"] = status

        st.write("Parâmetros usados:")
        st.json(params)

        data = fetch_all(base_url, token, params)
        saved = save_punches(conn, data)

        set_meta(conn, "last_sync", str(now_ms()))

        st.success(f"{saved} registros atualizados.")

# ---------- EXPORT ----------
with col3:
    if st.button("📄 Exportar tudo em CSV"):
        df = pd.read_sql_query("SELECT * FROM punches ORDER BY date", conn)
        csv = df.to_csv(index=False)

        st.download_button(
            "⬇️ Baixar CSV",
            csv,
            file_name="tangerino_punches.csv",
            mime="text/csv"
        )

# =====================================================
# PREVIEW
# =====================================================

st.markdown("---")
st.subheader("📋 Últimos registros")

df_preview = pd.read_sql_query(
    "SELECT id, employeeId, date, status, lastModifiedDate FROM punches ORDER BY saved_at DESC LIMIT 100",
    conn
)

st.dataframe(df_preview)
