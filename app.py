import requests

url = "https://employer.tangerino.com.br/test"

headers = {
    "accept": "application/json;charset=UTF-8",
    "Authorization": "Basic YzM1MDM5MDEyNThhNGU3MGIyYmM4ZjA0NWU0ZTAyYWY6MzE3MmU3M2Y0YTQ2NDliNmE0ZTJhYzFlMjViN2JhMGU="
}

response = requests.get(url, headers=headers, timeout=20)

print("Status:", response.status_code)
print("Body:", response.text)
