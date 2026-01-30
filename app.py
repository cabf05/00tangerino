import os
import time
import json
import sqlite3
from datetime import datetime, timezone

import streamlit as st
import requests
import pandas as pd

# =====================
# CONFIG
# =====================

BASE_URL_DEFAULT = "https://apis.tangerino.com.br/punch"
DB_PATH = "punches.db"
ENV_TOKEN_NAME = "TANGERINO_TOKEN"

# =====================
# DATABASE
# =====================

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
    cur.execute("SELECT value FROM metadata WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def set_meta(conn, key, value):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO metadata (key,value) VALUES (?,?)",
        (key, value),
    )
    conn.commit()


def save_punches(conn, punches):
    cur = conn.cursor()
    now_ms = int(time.time() * 1000)

    for p in punches:
        cur.execute("""
            INSERT OR REPLACE INTO punches
            (id, employeeId, date, status, lastModifiedDate, raw_json, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            p.get("id"),
            p.get("employeeId") or (p.get("employee") or {}).get("id"),
            p.get("date"),
            p.get("status"),
            p.get("lastModifiedDate"),
            json.dumps(p, ensure_ascii=False),
            now_ms
        ))

    conn.commit()
    return len(punches)

# =====================
# API
# =====================

def fetch_punches(base_url, token, last_update, page_size=200):
    headers = {
        "Authorization": token,
        "Accept": "application/json"
    }

    page = 0
    all_data = []

    while True:
        params = {
            "lastUpdate": last_update,
            "page": page,
            "size": page_size
        }

        r = requests.get(base_url, headers=headers, params=params, timeout=30)
        r.raise_for_status()

        data = r.json()
        content = data.get("content", [])

        if not content:
            break

        all_data.extend(content)

        if data.get("last") is True:
            break

        page += 1

    return all_data

# =====================
# UTILS
# =====================

def now_ms():
    return int(time.time() * 1000)

def ms_to_local(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().isoformat()

# =====================
# STREAMLIT UI
# =====================

st.set_page_config("Tangerino Sync", layout="wide")
st.title("📊 Tangerino – Sync incremental de pontos")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
init_db(conn)

# ===== TOKEN =====

env_token = os.getenv(ENV_TOKEN_NAME)

with st.sidebar:
    st.header("Configuração")

    base_url = st.text_input("Base URL", BASE_URL_DEFAULT)

    if env_token:
        st.success("Token carregado da variável de ambiente ✅")
        token = env_token
    else:
        st.warning("Variável TANGERINO_TOKEN não encontrada")
        token = st.text_area("Cole o token manualmente")

    page_size = st.number_input("Page size", 50, 1000, 200, 50)

# ===== LAST SYNC =====

raw_last = get_meta(conn, "last_sync")
if raw_last:
    st.info(f"Último sync: {ms_to_local(int(raw_last))}")
else:
    st.info("Nenhum sync ainda (primeira execução)")

# =====================
# ACTIONS
# =====================

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🔄 Sync incremental"):
        last_ms = int(raw_last) if raw_last else 0

        st.write(f"Buscando desde: {last_ms}")
        data = fetch_punches(base_url, token, last_ms, page_size)

        saved = save_punches(conn, data)
        set_meta(conn, "last_sync", str(now_ms()))

        st.success(f"{saved} pontos sincronizados.")

with col2:
    if st.button("📥 Sync completo (lastUpdate=0)"):
        data = fetch_punches(base_url, token, 0, page_size)
        saved = save_punches(conn, data)
        set_meta(conn, "last_sync", str(now_ms()))
        st.success(f"{saved} pontos importados.")

with col3:
    if st.button("📄 Exportar TUDO em CSV"):
        df = pd.read_sql_query("SELECT * FROM punches ORDER BY date", conn)
        csv = df.to_csv(index=False)

        st.download_button(
            "⬇️ Baixar CSV completo",
            csv,
            file_name="tangerino_punches_full.csv",
            mime="text/csv"
        )

# =====================
# PREVIEW
# =====================

st.markdown("---")
st.subheader("📋 Últimos 50 registros")

df_preview = pd.read_sql_query(
    "SELECT id, employeeId, date, status, lastModifiedDate FROM punches ORDER BY saved_at DESC LIMIT 50",
    conn
)

st.dataframe(df_preview)
