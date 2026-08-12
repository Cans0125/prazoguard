import base64
import requests

API_URL = "https://evolution-api-production-01fc.up.railway.app/send/Text/main"
API_TOKEN = "1244ea2d9c1f8c07c85edc34ed8c27a7a3579e171a453ca478396b2f6c22f091"

def resetar_e_gerar_novo_qrcode():
    headers = {
        "apikey": API_TOKEN,
        "Content-Type": "application/json"
    }
    
    # 1. Deleta a instância antiga travada (se existir)
    print("Removendo instância antiga (caso exista)...")
    requests.delete(f"{API_URL}/instance/delete/main", headers=headers)
    
    # 2. Cria uma nova instância limpa pedindo o QR Code
    print("Criando uma nova instância 'main'...")
    url_create = f"{API_URL}/instance/create"
    payload = {
        "instanceName": "main",
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS"
    }
    
    response = requests.post(url_create, json=payload, headers=headers)
    
    if response.status_code in [200, 201]:
        dados = response.json()
        print("\n✅ Nova instância criada com sucesso!")
        
        try:
            base64_str = (
                dados.get("base64") or 
                dados.get("qrcode", {}).get("base64")
            )
            
            if base64_str:
                if "," in base64_str:
                    base64_str = base64_str.split(",")[1]
                    
                img_data = base64.b64decode(base64_str)
                with open("qrcode.png", "wb") as fh:
                    fh.write(img_data)
                print("\n🎉 PRONTO! Um novo arquivo 'qrcode.png' foi gerado na sua pasta.")
                print("Abra a imagem imediatamente e escaneie com o WhatsApp do seu celular.")
            else:
                print("\n🔍 Resposta da API:", dados)
        except Exception as e:
            print(f"\n❌ Erro ao salvar a imagem: {e}")
    else:
        print(f"\n❌ Erro ao criar: {response.text}")

if __name__ == "__main__":
    resetar_e_gerar_novo_qrcode()