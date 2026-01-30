import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Tangerino → CSV", layout="wide")

st.title("Exportar Punch da Tangerino")

URL = "https://apis.tangerino.com.br/punch/?page=0&size=50"

headers = {
    "accept": "application/json;charset=UTF-8",
    "Authorization": st.secrets["TANGERINO_AUTH"]
}

if st.button("Buscar dados"):
    with st.spinner("Buscando dados da Tangerino..."):
        r = requests.get(URL, headers=headers, timeout=30)

    if r.status_code != 200:
        st.error(f"Erro {r.status_code}")
        st.code(r.text)
        st.stop()

    data = r.json()

    # pega a lista correta
    records = data.get("content", [])

    if not records:
        st.warning("Nenhum registro encontrado")
        st.stop()

    df = pd.json_normalize(records, sep="_")

    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "📥 Baixar CSV",
        csv,
        file_name=f"tangerino_punch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv"
    )
