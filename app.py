import os
import json
import time
import sqlite3
from datetime import datetime, timedelta

import streamlit as st
import requests
import pandas as pd

# =====================================================
# CONFIG
# =====================================================

BASE_URL_DEFAULT = "https://apis.tangerino.com.br/punch"
DB_FILE = "punches.db"

# =====================================================
# DATABASE
# =====================================================

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS punches (
        id INTEGER PRIMARY KEY,
        employeeId INTEGER,
        date TEXT,
        status TEXT,
        lastModifiedDate TEXT,
        raw_json TEXT,
        inserted_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    return conn

def get_meta(conn, key):
    cur = conn.cursor()
    cur.execute("SELECT value FROM metadata WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else None

def set_meta(conn, key, value):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO metadata (key,value) VALUES (?,?)",
        (key, value)
    )
    conn.commit()

def save_punches(conn, punches):
    cur = conn.cursor()
    now = int(time.time() * 1000)
    total = 0

    for p in punches:
        cur.execute("""
        INSERT OR REPLACE INTO punches
        (id, employeeId, date, status, lastModifiedDate, raw_json, inserted_at)
        VALUES (?,?,?,?,?,?,?)
        """, (
            p.get("id"),
            p.get("employeeId"),
            p.get("date"),
            p.get("status"),
            p.get("lastModifiedDate"),
            json.dumps(p, ensure_ascii=False),
            now
        ))
        total += 1

    conn.commit()
    return total

# =====================================================
# API
# =====================================================

def call_api(url, token, params):
    headers = {
        "Authorization": token,
        "Accept": "application/json"
    }

    r = requests.get(url, headers=headers, params=params, timeout=40)

    st.code(f"URL chamada:\n{r.url}")

    if not r.ok:
        st.error(f"HTTP {r.status_code}")
        try:
            st.json(r.json())
        except:
            st.text(r.text)
        raise Exception("Erro na API")

    return r.json()

def fetch_all(url, token, params):
    page = 0
    results = []

    while True:
        p = params.copy()
        p["page"] = page

        data = call_api(url, token, p)

        items = data.get("content")

        if not items:
            break

        results.extend(items)

        if data.get("last") is True:
            break

        page += 1

    return results

# =====================================================
# STREAMLIT UI
# =====================================================

st.set_page_config("Tangerino Punch Sync", layout="wide")
st.title("📊 Tangerino — Sync de registros de ponto")

conn = init_db()

# =====================================================
# TOKEN
# =====================================================

token = st.secrets.get("TANGERINO_TOKEN") or os.getenv("TANGERINO_TOKEN")

if not token:
    st.error("Configure TANGERINO_TOKEN nos Secrets do Streamlit")
    st.stop()

# =====================================================
# SIDEBAR
# =====================================================

with st.sidebar:
    st.header("⚙️ Configuração")

    base_url = st.text_input("Endpoint", BASE_URL_DEFAULT)

    st.markdown("### 📅 Período")

    start_date = st.date_input(
        "Data inicial",
        datetime.today().date() - timedelta(days=30)
    )

    end_date = st.date_input(
        "Data final",
        datetime.today().date()
    )

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    st.markdown("### 🔍 Filtros")

    status = st.selectbox(
        "Status",
        ["", "APPROVED", "PENDING", "REPROVED"]
    )

    employee_id = st.text_input("Employee ID (opcional)")

    page_size = st.number_input(
        "Page size",
        50,
        1000,
        200,
        step=50
    )

# =====================================================
# LAST UPDATE
# =====================================================

last_sync = get_meta(conn, "last_sync")

if last_sync:
    st.info(f"Último incremental: {datetime.fromtimestamp(int(last_sync)/1000)}")
else:
    st.info("Nenhum sync incremental executado")

# =====================================================
# BUTTONS
# =====================================================

c1, c2, c3 = st.columns(3)

# ---------- FULL LOAD ----------
with c1:
    if st.button("📥 Carga completa"):
        params = {
            "startDate": start_str,
            "endDate": end_str,
            "size": page_size
        }

        if status:
            params["status"] = status

        if employee_id:
            params["employeeId"] = employee_id

        st.json(params)

        punches = fetch_all(base_url, token, params)
        saved = save_punches(conn, punches)

        set_meta(conn, "last_sync", str(int(time.time() * 1000)))

        st.success(f"{saved} registros importados")

# ---------- INCREMENTAL ----------
with c2:
    if st.button("🔄 Sync incremental"):
        if not last_sync:
            st.warning("Execute uma carga completa primeiro")
            st.stop()

        params = {
            "lastUpdate": int(last_sync),
            "size": page_size
        }

        if status:
            params["status"] = status

        st.json(params)

        punches = fetch_all(base_url, token, params)
        saved = save_punches(conn, punches)

        set_meta(conn, "last_sync", str(int(time.time() * 1000)))

        st.success(f"{saved} registros atualizados")

# ---------- EXPORT ----------
with c3:
    if st.button("📄 Exportar CSV"):
        df = pd.read_sql_query("SELECT * FROM punches ORDER BY date", conn)
        csv = df.to_csv(index=False)

        st.download_button(
            "⬇️ Download CSV",
            csv,
            file_name="tangerino_punches.csv",
            mime="text/csv"
        )

# =====================================================
# PREVIEW
# =====================================================

st.markdown("---")
st.subheader("📋 Últimos registros")

preview = pd.read_sql_query(
    "SELECT id, employeeId, date, status, lastModifiedDate FROM punches ORDER BY inserted_at DESC LIMIT 100",
    conn
)

st.dataframe(preview)
