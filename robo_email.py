# robo_email.py
import imaplib, email, os, time
from logic import analisar_com_gemini, salvar_no_banco, enviar_alertas
from dotenv import load_dotenv

load_dotenv()

# Use o .env para a senha! Nunca cole a senha aqui.
EMAIL_USER = os.getenv("EMAIL_USER") 
EMAIL_PASS = os.getenv("EMAIL_PASS") 

def monitorar_email():
    # ... (seu código de conectar ao gmail igual estava) ...
    # Quando chegar na parte de ter o corpo_texto:
    
    if corpo_texto.strip():
        print("🤖 Robô: Processando com IA...")
        try:
            dados = analisar_com_gemini(corpo_texto)
            salvar_no_banco(dados)
            enviar_alertas(dados, "denerpneto@hotmail.com", "5531999996982")
            print(f"✅ Processo {dados['processo']} notificado!")
        except Exception as e:
            print(f"Erro: {e}")

# ... (seu loop while True continua igual) ...