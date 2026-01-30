import streamlit as st
import requests
import pandas as pd

# ---------------------------
# Configurações
# ---------------------------
BASE_URL = "https://apis.tangerino.com.br/punch/"  # note a barra no final
TOKEN = st.secrets.get("TANGERINO_TOKEN", "")

HEADERS = {
    "Authorization": TOKEN,
    "Accept": "application/json;charset=UTF-8",
}

st.title("Teste de integração com Tangerino")

# ---------------------------
# Parâmetros (filtros)
# ---------------------------
params = {
    "size": 10,      # pegar apenas 10 para teste
    "page": 0
}

st.write("Buscando punches...")

# ---------------------------
# Requisição
# ---------------------------
try:
    response = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
    st.write("Status code:", response.status_code)

    response.raise_for_status()  # lança exceção se não for 2xx

    data = response.json()
    punches = data.get("content", [])

    if not punches:
        st.warning("Nenhum punch retornado")
    else:
        df = pd.json_normalize(punches)
        st.dataframe(df.head(10))

        # Exportar CSV
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar CSV", csv, "punches.csv", "text/csv")

except requests.exceptions.HTTPError as err:
    st.error(f"Erro HTTP: {err} - {response.text}")
except Exception as e:
    st.error(f"Erro inesperado: {e}")
