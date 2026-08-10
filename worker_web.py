# worker_web.py
from flask import Flask
import imaplib
import email
import os
from email.header import decode_header
from dotenv import load_dotenv
from logic import analisar_com_gemini, salvar_no_banco, enviar_alertas

load_dotenv()

app = Flask(__name__)

IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
PASTA_DESTINO = "tribunal_inbox"

@app.route("/")
def verificar_emails_uma_vez():
    if not os.path.exists(PASTA_DESTINO):
        os.makedirs(PASTA_DESTINO)

    processados = 0
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            return "Nenhum e-mail novo encontrado.", 200

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
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                try:
                                    corpo_texto = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                                except Exception:
                                    pass
                            elif content_type == "text/html" and not corpo_texto:
                                try:
                                    corpo_texto = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                    else:
                        try:
                            corpo_texto = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass

                    if corpo_texto and corpo_texto.strip():
                        try:
                            dados = analisar_com_gemini(corpo_texto)
                            salvar_no_banco(dados)
                            enviar_alertas(
                                dados, 
                                os.getenv("EMAIL_PADRAO", "denerpneto@hotmail.com"), 
                                os.getenv("WHATSAPP_PADRAO", "5531999996982")
                            )
                            processados += 1
                        except Exception as e:
                            print(f"Erro ao processar: {e}")

            mail.store(num, "+FLAGS", "\\Seen")
        mail.logout()
        return f"Verificação concluída. {processados} e-mails processados.", 200
        
    except Exception as e:
        return f"Erro na conexão IMAP: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)