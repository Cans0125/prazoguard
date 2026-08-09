import requests

API_URL = "https://evolution-api-production-01fc.up.railway.app"
API_TOKEN = "1244ea2d9c1f8c07c85edc34ed8c27a7a3579e171a453ca478396b2f6c22f091"

def verificar_conexao():
    url = f"{API_URL}/instance/connectionState/main"
    headers = {
        "apikey": API_TOKEN
    }
    
    print("Verificando status da conexão no Railway...")
    response = requests.get(url, headers=headers)
    
    print("Resposta da API:", response.text)

if __name__ == "__main__":
    verificar_conexao()