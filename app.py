import os
import requests
import pandas as pd
import sqlite3
import streamlit as st
from datetime import datetime, timedelta

# ================================
# CONFIGURAÇÕES
# ================================
DB_FILE = "tangerino.db"
BASE_URL = "https://apis.tangerino.com.br/punch"

# Token vindo do secret do Streamlit
TOKEN = st.secrets.get("TANGERINO_TOKEN", "")
HEADERS = {"Authorization":TOKEN}

# ================================
# FUNÇÕES
# ================================

def init_db():
    """Inicializa o banco de dados, criando a tabela se não existir"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS punches (
            id INTEGER PRIMARY KEY,
            employeeId INTEGER,
            date TEXT,
            status TEXT,
            lastModifiedDate TEXT,
            inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

def fetch_page(params):
    """Busca uma página de punches da API"""
    response = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
    if response.status_code != 200:
        st.error(f"Erro na API: {response.status_code} - {response.text}")
        return None
    return response.json().get("content", [])

def save_punches(data):
    """Salva os punches no banco SQLite"""
    if not data:
        return 0
    df = pd.DataFrame(data)
    # Pega apenas colunas essenciais
    df = df[["id", "employeeId", "date", "status", "lastModifiedDate"]]
    with sqlite3.connect(DB_FILE) as conn:
        df.to_sql("punches", conn, if_exists="append", index=False)
    return len(df)

def fetch_all(last_update=None, page_size=200):
    """Busca todos os punches desde o last_update"""
    if last_update is None:
        last_update = 0  # default para sync completo
    page = 0
    total = 0
    while True:
        params = {"lastUpdate": last_update, "size": page_size, "page": page}
        st.write(f"🔄 Buscando página {page}...")
        punches = fetch_page(params)
        if punches is None:
            break
        count = save_punches(punches)
        total += count
        if len(punches) < page_size:
            break
        page += 1
    st.success(f"✅ Total de {total} punches importados.")

# ================================
# INTERFACE STREAMLIT
# ================================

st.title("Tangerino Punch Sync")

init_db()

st.sidebar.header("Filtros da sincronização")
sync_type = st.sidebar.selectbox("Tipo de sincronização", ["Completo", "Incremental"])
last_update_input = st.sidebar.text_input(
    "Último timestamp Unix para incremental (deixe vazio para usar 0)", ""
)

page_size = st.sidebar.number_input("Tamanho da página", min_value=50, max_value=500, value=200, step=50)

if st.sidebar.button("⏳ Sincronizar"):
    try:
        if sync_type == "Completo":
            last_update = 0
        else:
            last_update = int(last_update_input) if last_update_input.strip() else 0
        fetch_all(last_update, page_size)
    except Exception as e:
        st.error(f"Erro durante a sincronização: {e}")

# ================================
# PREVIEW SEGURO
# ================================
st.markdown("---")
st.subheader("📋 Preview dos últimos registros (limitado a 20)")

try:
    with sqlite3.connect(DB_FILE) as conn:
        preview_df = pd.read_sql_query(
            "SELECT id, employeeId, date, status, lastModifiedDate FROM punches ORDER BY inserted_at DESC LIMIT 20",
            conn
        )
    st.dataframe(preview_df)
except Exception as e:
    st.error(f"Erro ao carregar preview: {e}")

# ================================
# EXPORTAR CSV
# ================================
st.markdown("---")
st.subheader("📄 Exportar todos os registros para CSV")

try:
    with sqlite3.connect(DB_FILE) as conn:
        full_df = pd.read_sql_query(
            "SELECT id, employeeId, date, status, lastModifiedDate FROM punches ORDER BY inserted_at DESC",
            conn
        )
    st.download_button(
        label="⬇️ Download CSV",
        data=full_df.to_csv(index=False),
        file_name="tangerino_punches.csv",
        mime="text/csv"
    )
except Exception as e:
    st.error(f"Erro ao gerar CSV: {e}")
