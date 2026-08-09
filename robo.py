from datetime import datetime
import os
import time
from dotenv import load_dotenv
from supabase import create_client
import google.generativeai as genai
from pydantic import BaseModel, Field
from pypdf import PdfReader
import requests
import resend

# --- CARREGA AS CHAVES SECRETAS DO ARQUIVO .ENV ---
load_dotenv()

# Configuração do Supabase na nuvem (Substitui o SQLite)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- CONFIGURAÇÕES ---
API_KEY_GEMINI = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY_GEMINI)

# Configurações de Fallback
EMAIL_PADRAO = os.getenv("EMAIL_PADRAO", "denerpneto@hotmail.com")
WHATSAPP_PADRAO = os.getenv("WHATSAPP_PADRAO", "5531999996982")

# Configurações do Resend (E-mail)
resend.api_key = os.getenv("RESEND_API_KEY")

# Configurações da API de WhatsApp
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

# Pasta que o robô vai monitorar em segundo plano
PASTA_MONITORADA = "tribunal_inbox"


# Estrutura Pydantic para a IA
class Intimacao(BaseModel):
    processo: str = Field(description="Número do processo no padrão CNJ")
    advogado_ou_oab: str = Field(description="Nome do advogado ou número da OAB extraído do documento")
    prazo_dias: int = Field(description="Quantidade de dias do prazo processual")
    resumo: str = Field(description="Resumo claro e direto do que deve ser feito")


def analisar_com_gemini(texto_publicacao: str):
    model = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite",
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": Intimacao,
        },
        system_instruction="Você é um assistente jurídico sênior especializado em extrair prazos de Diários Oficiais e intimações."
    )
    response = model.generate_content(f"Analise a publicação e extraia os dados:\n\n{texto_publicacao}")
    return Intimacao.model_validate_json(response.text)


def buscar_contato_por_oab(oab_ou_nome):
    """Cruza a OAB/Nome extraída com o banco de dados de advogados no Supabase."""
    try:
        resposta = supabase.table("advogados").select("email, whatsapp").or_(f"oab.ilike.%{oab_ou_nome}%,nome.ilike.%{oab_ou_nome}%").execute()
        
        if resposta.data and len(resposta.data) > 0:
            return resposta.data[0]["email"], resposta.data[0]["whatsapp"]
    except Exception as e:
        print(f"Erro ao consultar Supabase de advogados: {e}")
        
    return EMAIL_PADRAO, WHATSAPP_PADRAO


def salvar_no_banco(processo, advogado_oab, prazo_dias, resumo):
    try:
        dados = {
            "processo": processo,
            "advogado_ou_oab": advogado_oab,
            "prazo_dias": prazo_dias,
            "resumo": resumo,
            "created_at": datetime.now().isoformat()
        }
        # Envia direto para a tabela processos na nuvem
        supabase.table("processos").insert(dados).execute()
    except Exception as e:
        print(f"Erro ao salvar no Supabase: {e}")


def enviar_alerta_email(email_destino, processo, advogado, prazo, resumo):
    try:
        corpo_email = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
            <h2 style="color: #1e3a8a;">⚖️ PrazoGuard - Alerta Automático de Intimação</h2>
            <p><b>Processo:</b> {processo}</p>
            <p><b>Advogado/OAB Responsável:</b> {advogado}</p>
            <p><b>Prazo Fatal:</b> <span style="color: #dc2626; font-weight: bold;">{prazo} dias úteis</span></p>
            <p><b>Resumo:</b> {resumo}</p>
        </div>
        """
        params = {
            "from": "PrazoGuard <onboarding@resend.dev>",
            "to": [email_destino],
            "subject": f"🚨 URGENTE: Prazo de {prazo} dias - Proc. {processo}",
            "html": corpo_email,
        }
        resend.Emails.send(params)
        print(f"📧 E-mail enviado com sucesso para {email_destino}")
    except Exception as e:
        print(f"Erro no e-mail: {e}")


def enviar_alerta_whatsapp(telefone_destino, processo, advogado, prazo, resumo):
    headers = {"apikey": WHATSAPP_TOKEN, "Content-Type": "application/json"}
    texto_msg = (
        f"🚨 *PRAZOGUARD - NOVO PRAZO AUTOMÁTICO* 🚨\n\n"
        f"📁 *Processo:* {processo}\n"
        f"⚖️ *Advogado/OAB:* {advogado}\n"
        f"⏳ *Prazo Fatal:* *{prazo} dias úteis*\n\n"
        f"📋 *Resumo:* {resumo}"
    )
    payload = {"number": telefone_destino, "text": texto_msg}
    try:
        response = requests.post(WHATSAPP_API_URL, json=payload, headers=headers)
        if response.status_code in [200, 201]:
            print(f"✅ WhatsApp enviado com sucesso para {telefone_destino}")
        else:
            print(f"Erro WhatsApp: {response.text}")
    except Exception as e:
        print(f"Erro de conexão WhatsApp: {e}")


def processar_arquivos():
    if not os.path.exists(PASTA_MONITORADA):
        os.makedirs(PASTA_MONITORADA)

    arquivos = os.listdir(PASTA_MONITORADA)
    if not arquivos:
        return

    for arquivo in arquivos:
        caminho_completo = os.path.join(PASTA_MONITORADA, arquivo)
        if os.path.isfile(caminho_completo):
            # Verifica se é PDF ou TXT
            if arquivo.lower().endswith((".pdf", ".txt")):
                print(f"\n📄 Novo arquivo detectado pelo robô: {arquivo}")

                try:
                    texto_extraido = ""
                    if arquivo.lower().endswith(".pdf"):
                        reader = PdfReader(caminho_completo)
                        for page in reader.pages:
                            texto_extraido += page.extract_text() or ""
                    else:
                        with open(caminho_completo, "r", encoding="utf-8") as f:
                            texto_extraido = f.read()

                    if not texto_extraido.strip():
                        print("⚠️ O arquivo está vazio.")
                        continue

                    print("🤖 Analisando documento com Gemini...")
                    resultado = analisar_com_gemini(texto_extraido)

                    salvar_no_banco(
                        resultado.processo,
                        resultado.advogado_ou_oab,
                        resultado.prazo_dias,
                        resultado.resumo,
                    )
                    print(f"💾 Processo {resultado.processo} gravado no Supabase (Nuvem).")

                    email_adv, whats_adv = buscar_contato_por_oab(
                        resultado.advogado_ou_oab
                    )
                    print(
                        f"🎯 Roteamento concluído: Direcionado para {email_adv} e {whats_adv}"
                    )

                    if resultado.prazo_dias > 0:
                        enviar_alerta_email(
                            email_adv,
                            resultado.processo,
                            resultado.advogado_ou_oab,
                            resultado.prazo_dias,
                            resultado.resumo,
                        )
                        enviar_alerta_whatsapp(
                            whats_adv,
                            resultado.processo,
                            resultado.advogado_ou_oab,
                            resultado.prazo_dias,
                            resultado.resumo,
                        )

                    pasta_processados = os.path.join(PASTA_MONITORADA, "processados")
                    if not os.path.exists(pasta_processados):
                        os.makedirs(pasta_processados)
                    os.rename(
                        caminho_completo, os.path.join(pasta_processados, arquivo)
                    )
                    print(f"✔️ Arquivo {arquivo} processado e arquivado com sucesso!\n")

                except Exception as e:
                    print(f"❌ Erro ao processar o arquivo {arquivo}: {e}")


if __name__ == "__main__":
    print(f"🤖 Robô de automação PrazoGuard iniciado!")
    print(f"📂 Monitorando a pasta '{PASTA_MONITORADA}/' em segundo plano...")
    print("Pressione Ctrl+C para parar.\n")
    
    while True:
        processar_arquivos()
        time.sleep(5)  # Varre a pasta a cada 5 segundos