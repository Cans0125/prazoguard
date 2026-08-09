import os
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
import stripe
from supabase import create_client

load_dotenv()

app = FastAPI()

# Configurações do Stripe e Supabase
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
ENDPOINT_SECRET = os.getenv(
    "STRIPE_WEBHOOK_SECRET"
)  # A chave whsec_... que o terminal gerou

supabase = create_client(
    os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
)


@app.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
  payload = await request.body()

  try:
    # Valida se a requisição realmente veio do Stripe usando a assinatura de segurança
    event = stripe.Webhook.construct_event(
        payload, stripe_signature, ENDPOINT_SECRET
    )
  except ValueError as e:
    # Payload inválido
    raise HTTPException(status_code=400, detail="Invalid payload")
  except stripe.error.SignatureVerificationError as e:
    # Assinatura inválida (segurança violada)
    raise HTTPException(status_code=400, detail="Invalid signature")

  # Captura o evento de checkout concluído com sucesso
  if event["type"] == "checkout.session.completed":
    session = event["data"]["object"]

    email_cliente = session.get("customer_email")
    stripe_customer_id = session.get("customer")
    # Pega o tipo de plano através do metadado ou linha de item se necessário
    plano = "Ativo"

    if email_cliente:
      try:
        # Atualiza o Supabase automaticamente
        supabase.table("advogados").update({
            "subscription_status": "ativo",
            "stripe_customer_id": stripe_customer_id,
            "plan_type": plano,
        }).eq("email", email_cliente).execute()

        print(
            f"Sucesso: Assinatura ativada para o e-mail {email_cliente} no"
            " Supabase."
        )
      except Exception as db_error:
        print(f"Erro ao atualizar o banco de dados: {db_error}")

  return {"status": "success"}