import streamlit as st
import requests

st.title("Teste Tangerino /test")

# URL corrigida com barra no final
url = "https://apis.tangerino.com.br/punch"

# Headers incluindo User-Agent
headers = {
    "accept": "application/json;charset=UTF-8",
    "Authorization": st.secrets["TANGERINO_AUTH"]
    #"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

if st.button("Testar endpoint"):
    st.write("Fazendo request...")

    try:
        # Fazendo request GET
        response = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        st.error(e)
        st.stop()

    st.write("Status:", response.status_code)
    st.write("Headers:", dict(response.headers))
    st.code(response.text if response.text else "(resposta vazia)")
