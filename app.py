import streamlit as st
import requests

st.title("Teste Tangerino /test")

url = "https://apis.tangerino.com.br/punch/?adjustment=true&startDate=1769716800000&endDate=1769803199000&page=0&size=100"

headers = {
    "accept": "application/json;charset=UTF-8",
    "Authorization": st.secrets["TANGERINO_AUTH"]
}

if st.button("Testar endpoint"):
    st.write("Fazendo request...")

    try:
        response = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        st.error(e)
        st.stop()

    st.write("Status:", response.status_code)
    st.write("Headers:", dict(response.headers))
    st.code(response.text if response.text else "(resposta vazia)")
