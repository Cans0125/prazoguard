from email.header import decode_header
import email
import imaplib
import os
import time

# --- CONFIGURAÇÕES DE E-MAIL ---
# Se usar Gmail, o servidor é imap.gmail.com. Se for Outlook/Hotmail, outlook.office365.com
IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = "denerpereiraneto@gmail.com"
EMAIL_PASS = (
    "vhokmntrpssakzob"  # IMPORTANTE: Use uma Senha de App do Google
)
PASTA_DESTINO = "tribunal_inbox"


def monitorar_email():
  if not os.path.exists(PASTA_DESTINO):
    os.makedirs(PASTA_DESTINO)

  try:
    # Conecta ao servidor IMAP com SSL
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    # Busca apenas e-mails não lidos (UNSEEN)
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

          # Decodifica o assunto do e-mail
          subject, encoding = decode_header(msg["Subject"])[0]
          if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="ignore")

          print(f"📧 Novo e-mail detectado: {subject}")

          tem_anexo_pdf = False

          # Varre o e-mail procurando anexos PDF
          for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition"))
            if "attachment" in content_disposition:
              filename = part.get_filename()
              if filename:
                decoded_filename = decode_header(filename)[0]
                if isinstance(decoded_filename[0], bytes):
                  filename = decoded_filename[0].decode(
                      decoded_filename[1] or "utf-8", errors="ignore"
                  )
                else:
                  filename = decoded_filename[0]

                if filename.lower().endswith(".pdf"):
                  filepath = os.path.join(PASTA_DESTINO, filename)
                  with open(filepath, "wb") as f:
                    f.write(part.get_payload(decode=True))
                  print(f"📥 Anexo PDF salvo na pasta: {filename}")
                  tem_anexo_pdf = True

          # Se o e-mail não tiver PDF em anexo, salva o corpo do texto do e-mail
          if not tem_anexo_pdf:
            corpo_texto = ""
            if msg.is_multipart():
              for part in msg.walk():
                if part.get_content_type() == "text/plain":
                  corpo_texto = part.get_payload(decode=True).decode(
                      "utf-8", errors="ignore"
                  )
                  break
            else:
              corpo_texto = msg.get_payload(decode=True).decode(
                  "utf-8", errors="ignore"
              )

            if corpo_texto.strip():
              nome_arquivo = f"intimacao_{int(time.time())}.txt"
              filepath = os.path.join(PASTA_DESTINO, nome_arquivo)
              with open(filepath, "w", encoding="utf-8") as f:
                f.write(corpo_texto)
              print(f"📥 Conteúdo do e-mail salvo como texto: {nome_arquivo}")

    mail.store(num, "+FLAGS", "\\Seen")

    mail.logout()
  except Exception as e:
    print(f"Erro na conexão de e-mail: {e}")


if __name__ == "__main__":
  print("🤖 Robô de E-mail do PrazoGuard Ativado!")
  print("Monitorando a caixa de entrada por novas intimações...\n")
  while True:
    monitorar_email()
    time.sleep(30)  # Verifica novos e-mails a cada 30 segundos