# robo_email.py
import imaplib
import email
import os
import time
from email.header import decode_header
from dotenv import load_dotenv
from logic import analisar_com_gemini, salvar_no_banco, enviar_alertas

load_dotenv()

IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")  # Certifique-se de usar a Senha de App do Google aqui
PASTA_DESTINO = "tribunal_inbox"

def monitorar_email():
    if not os.path.exists(PASTA_DESTINO):
        os.makedirs(PASTA_DESTINO)

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            return

        for num in messages[0].split():
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue

            for response_part in data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    corpo_texto = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                corpo_texto = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                    else:
                        corpo_texto = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                    if corpo_texto.strip():
                        print("🤖 Robô: E-mail novo detectado! Processando com IA...")
                        try:
                            # Processa com o Gemini, salva no Supabase e dispara os alertas
                            dados = analisar_com_gemini(corpo_texto)
                            salvar_no_banco(dados)
                            enviar_alertas(
                                dados, 
                                os.getenv("EMAIL_PADRAO", "denerpneto@hotmail.com"), 
                                os.getenv("WHATSAPP_PADRAO", "5531999996982")
                            )
                            print(f"✅ Sucesso! Processo {dados.get('processo')} processado e notificado.")
                        except Exception as e:
                            print(f"❌ Erro ao processar o conteúdo do e-mail: {e}")

            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        print(f"Erro na conexão de e-mail IMAP: {e}")

if __name__ == "__main__":
    print("🤖 Robô de E-mail do PrazoGuard Ativado!")
    print("Monitorando a caixa de entrada por novas intimações...\n")
    while True:
        monitorar_email()
        time.sleep(30)