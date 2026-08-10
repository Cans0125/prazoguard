# logic.py
import os
import json
import resend
import requests
import google.generativeai as genai
from supabase import create_client
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
resend.api_key = os.getenv("RESEND_API_KEY")

from pydantic import BaseModel, Field

class Intimacao(BaseModel):
    processo: str = Field(description="Número do processo no padrão CNJ")
    advogado_ou_oab: str = Field(description="Nome do advogado ou número da OAB")
    prazo_dias: int = Field(description="Quantidade de dias do prazo processual")
    resumo: str = Field(description="Resumo claro e direto do que deve ser feito")

def analisar_com_gemini(texto):
    print("🧠 IA: Iniciando análise...")
    model = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite",
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": Intimacao,
        }
    )
    
    response = model.generate_content(f"Analise a intimação e extraia os dados:\n\n{texto}")
    
    if not response.text:
        raise ValueError("A IA retornou uma resposta vazia.")
        
    print(f"🤖 IA respondeu com sucesso.")
    
    # O Pydantic garante que o retorno seja um JSON perfeitamente válido
    return json.loads(response.text.strip())

def salvar_no_banco(dados):
    print(f"💾 Banco: Salvando processo {dados.get('processo')}...")
    response = supabase.table("processos").insert({
        "processo": dados.get("processo"),
        "advogado_ou_oab": dados.get("advogado_ou_oab"),
        "prazo_dias": dados.get("prazo_dias"),
        "resumo": dados.get("resumo"),
        "status_kanban": "Nova Intimação"
    }).execute()
    print("✅ Banco: Salvo com sucesso.")

def enviar_alertas(dados, email_usuario, tel_whatsapp):
    print(f"📧 Resend: Tentando enviar e-mail para {email_usuario}...")
    try:
        res = resend.Emails.send({
            "from": "PrazoGuard <onboarding@resend.dev>",
            "to": [email_usuario],
            "subject": f"🚨 Prazo: Processo {dados.get('processo')}",
            "html": f"<h3>Novo Prazo</h3><p><b>Processo:</b> {dados.get('processo')}</p>"
        })
        print(f"✅ E-mail enviado! ID: {res['id']}")
    except Exception as e:
        print(f"❌ ERRO RESEND: {e}")

    print(f"📱 WhatsApp: Tentando enviar para {tel_whatsapp}...")
    try:
        payload = {
            "number": tel_whatsapp, 
            "text": f"🚨 *NOVO PRAZO* 🚨\nProcesso: {dados.get('processo')}\nResumo: {dados.get('resumo')}"
        }
        resp = requests.post(
            os.getenv("WHATSAPP_API_URL"), 
            json=payload, 
            headers={"apikey": os.getenv("WHATSAPP_TOKEN"), "Content-Type": "application/json"}
        )
        print(f"✅ WhatsApp respondeu: {resp.status_code}")
    except Exception as e:
        print(f"❌ ERRO WHATSAPP: {e}")