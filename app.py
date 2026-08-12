import os
import json
import uuid
import base64
from io import BytesIO
from datetime import datetime, timezone
from dotenv import load_dotenv

# --- CARREGA AS CHAVES SECRETAS PRIMEIRO ---
load_dotenv()

import streamlit as st
import pandas as pd
import requests
import resend
import stripe
from PIL import Image
import streamlit.components.v1 as components
from pypdf import PdfReader
import google.generativeai as genai
from supabase import create_client

# --- IMPORTAÇÕES DO ARQUIVO CENTRAL (logic.py) ---
from logic import analisar_com_gemini, salvar_no_banco, enviar_alertas, obter_qr_code_evolution

# --- PARTE SEGURA CONFIGURADA DO GOOGLE ANALYTICS ---
measurement_id = os.environ.get("GA_MEASUREMENT_ID", "G-2C08DBH6ZW")
api_secret = os.environ.get("GA_API_SECRET", "yom4EITQR5eKX5MgLBjNsg") 
base_url = "https://www.google-analytics.com/mp/collect"
url_ga = f"{base_url}?measurement_id={measurement_id}&api_secret={api_secret}"

payload_ga = {
    "client_id": str(uuid.uuid4()),  
    "events": [{
        "name": "execucao_script_python",  
        "params": {
            "tecnologia": "python_backend",
            "ambiente": "render"
        }
    }]
}

try:
    requests.post(url_ga, data=json.dumps(payload_ga), headers={'Content-Type': 'application/json'}, timeout=5)
except Exception:
    pass

st.set_page_config(
    page_title="PrazoGuard - Gestão Inteligente de Prazos",
    page_icon="⚖️",
    layout="wide",
)

def processar_novos_emails():
    import imaplib
    import email
    
    IMAP_SERVER = "outlook.office365.com"
    EMAIL_USER = os.getenv("EMAIL_USER")
    EMAIL_PASS = os.getenv("EMAIL_PASS")
    
    if not EMAIL_USER or not EMAIL_PASS:
        return

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
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
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))
                            
                            if "attachment" in content_disposition or part.get_filename():
                                filename = part.get_filename()
                                if filename and filename.lower().endswith(".pdf"):
                                    try:
                                        pdf_bytes = part.get_payload(decode=True)
                                        if pdf_bytes:
                                            reader = PdfReader(BytesIO(pdf_bytes))
                                            texto_pdf = ""
                                            for page in reader.pages:
                                                texto_pdf += page.extract_text() or ""
                                            if texto_pdf.strip():
                                                corpo_texto = texto_pdf
                                                break
                                    except Exception as e:
                                        print(f"Erro ao ler PDF anexo: {e}")
                            
                            elif content_type == "text/plain" and not corpo_texto:
                                try:
                                    corpo_texto = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except:
                                    pass
                    else:
                        try:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                corpo_texto = payload.decode("utf-8", errors="ignore")
                        except:
                            pass

                    if corpo_texto and corpo_texto.strip():
                        try:
                            print(f"🤖 Processando conteúdo com IA...")
                            dados = analisar_com_gemini(corpo_texto)
                            salvar_no_banco(dados)
                            
                            enviar_alertas(
                                dados, 
                                os.getenv("EMAIL_PADRAO", EMAIL_USER), 
                                os.getenv("WHATSAPP_PADRAO", "5531999996982")
                            )
                            print("✅ Alertas disparados com sucesso!")
                        except Exception as e:
                            print(f"❌ Erro ao processar dados: {e}")

            mail.store(num, "+FLAGS", "\\Seen")
        mail.logout()
    except Exception as e:
        print(f"❌ Erro na conexão IMAP: {e}")

# Executa a varredura automaticamente assim que o site abre
processar_novos_emails()

# Configuração do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- CONFIGURAÇÕES DO GEMINI E STRIPE ---
API_KEY_GEMINI = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY_GEMINI)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Configuração do Resend e WhatsApp Padrão
EMAIL_PADRAO = os.getenv("EMAIL_PADRAO", "denerpneto@hotmail.com")
WHATSAPP_PADRAO = os.getenv("WHATSAPP_PADRAO", "5531999996982")

WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

def gerar_minuta_com_gemini(processo, resumo):
    model = genai.GenerativeModel(model_name="gemini-3.1-flash-lite")
    prompt = (
        f"Com base no processo número {processo} e no resumo da intimação: '{resumo}',"
        " elabore uma minuta de petição preliminar profissional e formal, pronta"
        " para revisão do advogado."
    )
    response = model.generate_content(prompt)
    return response.text

def checar_status_assinatura(user_id, email):
    try:
        resposta = (
            supabase.table("advogados")
            .select("subscription_status, created_at")
            .eq("user_id", user_id)
            .execute()
        )

        if resposta.data and len(resposta.data) > 0:
            adv = resposta.data[0]
            status = adv.get("subscription_status", "inativo")
            if status == "ativo":
                return "ativo"

            created_at_str = adv.get("created_at")
            if created_at_str:
                data_limpa = created_at_str.replace("Z", "+00:00")
                data_criacao = datetime.fromisoformat(data_limpa)
                if data_criacao.tzinfo is None:
                    dias = (datetime.now() - data_criacao.replace(tzinfo=None)).days
                else:
                    dias = (datetime.now(timezone.utc) - data_criacao).days

                if dias <= 30:
                    return "trial"
        else:
            dados = {
                "user_id": user_id,
                "nome": "Novo Advogado",
                "oab": "Pendente",
                "email": email,
                "whatsapp": WHATSAPP_PADRAO,
                "subscription_status": "inativo",
                "created_at": datetime.now().isoformat(),
            }
            supabase.table("advogados").insert(dados).execute()
            return "trial"
    except Exception as e:
        print(f"Erro ao checar status: {e}")
        return "trial"
    return "inativo"

def atualizar_status_kanban(processo_id, novo_status):
    try:
        supabase.table("processos").update({"status_kanban": novo_status}).eq(
            "id", processo_id
        ).execute()
    except Exception as e:
        st.error(f"Erro ao atualizar Kanban: {e}")

estilo_css = """
<style>
.stApp { background-color: #ffffff; }
h1 { color: #0f172a; font-weight: 700; font-size: 2.2rem !important; }
h3 { color: #334155; font-weight: 600; }
div[data-testid="stMetric"] {
    background-color: rgba(255, 255, 255, 0.9);
    border: 1px solid #e2e8f0;
    padding: 18px 24px;
    border-radius: 10px;
}
.stButton button {
    background-color: #1e3a8a;
    color: white;
    border-radius: 8px;
    font-weight: 600;
    border: none;
}
.stButton button:hover { background-color: #1d4ed8; color: white; }
section[data-testid="stSidebar"] { background-color: #0f172a; color: #f8fafc; }
</style>
"""
st.markdown(estilo_css, unsafe_allow_html=True)

if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("⚖️ PrazoGuard - Acesso ao Sistema")
    st.markdown(
        "<p style='color: #64748b; font-size: 1.1rem;'>Faça login ou crie sua"
        " conta para gerenciar seus prazos com inteligência artificial.</p>",
        unsafe_allow_html=True,
    )

    aba_login, aba_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Conta Gratuita"])

    with aba_login:
        with st.form("form_login"):
            email_login = st.text_input("E-mail cadastrado")
            senha_login = st.text_input("Senha", type="password")
            btn_entrar = st.form_submit_button(
                "Entrar no Sistema", use_container_width=True
            )

            if btn_entrar:
                if email_login and senha_login:
                    try:
                        res = supabase.auth.sign_in_with_password(
                            {"email": email_login, "password": senha_login}
                        )
                        if res.user:
                            st.session_state.user = res.user
                            st.success("Login realizado com sucesso!")
                            st.rerun()
                    except Exception as e:
                        st.error("Erro ao fazer login: verifique seu e-mail e senha.")
                else:
                    st.warning("Preencha todos os campos.")

    with aba_cadastro:
        with st.form("form_cadastro"):
            email_cad = st.text_input("E-mail para cadastro")
            senha_cad = st.text_input("Crie uma senha forte", type="password")
            btn_cadastrar = st.form_submit_button(
                "Criar Conta (30 dias Grátis)", use_container_width=True
            )

            if btn_cadastrar:
                if email_cad and senha_cad:
                    try:
                        res = supabase.auth.sign_up(
                            {"email": email_cad, "password": senha_cad}
                        )
                        if res.user:
                            st.success(
                                "Conta criada com sucesso! Você já pode fazer login na aba 'Entrar'."
                            )
                    except Exception as e:
                        st.error(f"Erro ao cadastrar: {e}")
                else:
                    st.warning("Preencha todos os campos.")

else:
    usuario_atual = st.session_state.user
    status_assinatura = checar_status_assinatura(
        usuario_atual.id, usuario_atual.email
    )

    query_params = st.query_params
    if "sucesso" in query_params and st.session_state.user:
        try:
            supabase.table("advogados").update({"subscription_status": "ativo"}).eq("user_id", st.session_state.user.id).execute()
            st.success("🎉 Pagamento realizado com sucesso! Assinatura ativada.")
        except Exception as e:
            print(f"Erro ao atualizar assinatura: {e}")

    st.title("⚖️ PrazoGuard")
    st.markdown(
        "<p style='color: #64748b; font-size: 1.1rem; margin-top: -10px;'>Plataforma Completa de Inteligência Jurídica e Gestão de Prazos.</p>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown("### 👤 Conta Ativa")
        st.write(f"**{usuario_atual.email}**")
        
        st.markdown("---")
        st.markdown("### 📞 Precisa de Ajuda?")
        st.markdown("Tem alguma dúvida ou encontrou algum problema? Fale com a gente:")
        st.markdown("📧 **denerpneto@hotmail.com**")
        
        st.markdown("---")
        if st.button("🚪 Sair / Logout", use_container_width=True):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    MEU_EMAIL_ADMIN = "denerpneto@hotmail.com"

    if usuario_atual and usuario_atual.email == MEU_EMAIL_ADMIN:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 📱 Painel Admin - WhatsApp")
        nome_instancia_input = st.sidebar.text_input("Nome da Instância:", value="prazoguard")

        if st.sidebar.button("🔄 Gerar QR Code de Conexão"):
            if WHATSAPP_API_URL and WHATSAPP_TOKEN:
                with st.spinner("Buscando QR Code na Evolution API..."):
                    img_qr, mensagem = obter_qr_code_evolution(WHATSAPP_API_URL, WHATSAPP_TOKEN, nome_instancia_input)
                    if img_qr:
                        st.sidebar.success("Escaneie o QR Code abaixo com o WhatsApp:")
                        st.sidebar.image(img_qr, use_container_width=True)
                    else:
                        st.sidebar.info(mensagem)
            else:
                st.sidebar.error("Configure WHATSAPP_API_URL e WHATSAPP_TOKEN no seu .env")

    if status_assinatura in ["ativo", "trial"]:
        if status_assinatura == "trial":
            st.info(
                "⏳ **Aviso de Período de Teste:** Você está utilizando o PrazoGuard em"
                " modo de testes gratuitos (30 dias). Aproveite todos os recursos!"
            )

        (
            aba_kanban,
            aba_tabela,
            aba_minutas,
            aba_cnj,
            aba_advogados,
        ) = st.tabs([
            "📌 Quadro Kanban",
            "📋 Tabela de Prazos",
            "✍️ Gerador de Minutas",
            "🔍 Consulta CNJ",
            "👥 Equipe",
        ])

       with st.sidebar:
            st.markdown("---")
            st.header("📥 Nova Intimação")
            
            # Abas na barra lateral para escolher entre PDF ou Texto
            tipo_entrada = st.radio("Forma de Envio:", ["📄 Enviar PDF", "📝 Colar Texto"], horizontal=True)
            
            texto_para_analisar = ""
            
            if tipo_entrada == "📄 Enviar PDF":
                arquivo_enviado = st.file_uploader("Arraste o PDF aqui:", type=["pdf"])
                if arquivo_enviado is not None:
                    try:
                        reader = PdfReader(arquivo_enviado)
                        for page in reader.pages:
                            texto_para_analisar += page.extract_text() or ""
                    except Exception as e:
                        st.error(f"Erro ao ler PDF: {e}")
            else:
                texto_entrada = st.text_area(
                    "Cole o texto da publicação:",
                    height=120,
                    placeholder="Cole o teor da intimação aqui...",
                )
                if texto_entrada.strip():
                    texto_para_analisar = texto_entrada

            if st.button("🤖 Processar e Notificar", use_container_width=True):
                if texto_para_analisar.strip():
                    with st.spinner("Analisando com IA, salvando e disparando alertas..."):
                        try:
                            # 1. Analisa com a IA (logic.py)
                            resultado = analisar_com_gemini(texto_para_analisar)
                            
                            # 2. Salva no Supabase (logic.py)
                            salvar_no_banco(resultado)
                            
                            # 3. Busca o WhatsApp correto do advogado logado
                            telefone_alvo = WHATSAPP_PADRAO
                            try:
                                resp_adv = (
                                    supabase.table("advogados")
                                    .select("whatsapp")
                                    .eq("user_id", usuario_atual.id)
                                    .execute()
                                )
                                if resp_adv.data and len(resp_adv.data) > 0:
                                    telefone_alvo = resp_adv.data[0].get("whatsapp", WHATSAPP_PADRAO)
                            except Exception:
                                pass

                            # 4. Dispara os alertas (E-mail + WhatsApp via Railway)
                            enviar_alertas(resultado, usuario_atual.email, telefone_alvo)

                            st.success(f"Processo {resultado.get('processo')} processado com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao processar: {e}")
                else:
                    st.warning("Por favor, envie um PDF ou cole um texto válido antes de processar.")

        with aba_kanban:
            st.subheader("📌 Fluxo de Trabalho (Kanban)")
            if not df_processos.empty:
                col_k1, col_k2, col_k3 = st.columns(3)
                if "status_kanban" not in df_processos.columns:
                    df_processos["status_kanban"] = "Nova Intimação"

                with col_k1:
                    st.markdown("### 📥 Nova Intimação")
                    novos = df_processos[df_processos["status_kanban"] == "Nova Intimação"]
                    for _, row in novos.iterrows():
                        with st.container(border=True):
                            st.write(f"**Proc:** {row['processo']}")
                            st.write(f"**Prazo:** {row['prazo_dias']} dias")
                            st.write(f"*{row['resumo'][:80]}...*")
                            if st.button("Mover ➡️ Em Andamento", key=f"m1_{row['id']}"):
                                atualizar_status_kanban(row["id"], "Em Andamento")
                                st.rerun()

                with col_k2:
                    st.markdown("### ⏳ Em Andamento")
                    andamento = df_processos[df_processos["status_kanban"] == "Em Andamento"]
                    for _, row in andamento.iterrows():
                        with st.container(border=True):
                            st.write(f"**Proc:** {row['processo']}")
                            st.write(f"**Prazo:** {row['prazo_dias']} dias")
                            st.write(f"*{row['resumo'][:80]}...*")
                            if st.button("✅ Concluir", key=f"m2_{row['id']}"):
                                atualizar_status_kanban(row["id"], "Protocolado")
                                st.rerun()

                with col_k3:
                    st.markdown("### ✅ Protocolado")
                    protocolados = df_processos[df_processos["status_kanban"] == "Protocolado"]
                    for _, row in protocolados.iterrows():
                        with st.container(border=True):
                            st.write(f"**Proc:** {row['processo']}")
                            st.write(f"**Prazo:** {row['prazo_dias']} dias")
                            st.success("Finalizado")
            else:
                st.info("Nenhum processo cadastrado para o Kanban.")

        with aba_tabela:
            st.subheader("📋 Lista Completa de Prazos")
            if not df_processos.empty:
                st.dataframe(df_processos, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum registro encontrado.")

        with aba_minutas:
            st.subheader("✍️ Gerador de Minutas Preliminares com IA")
            if not df_processos.empty:
                lista_procs = df_processos["processo"].tolist()
                proc_escolhido = st.selectbox(
                    "Escolha o Número do Processo:", lista_procs
                )
                dado_proc = df_processos[
                    df_processos["processo"] == proc_escolhido
                ].iloc[0]
                st.info(f"**Resumo do Processo:** {dado_proc['resumo']}")

                if st.button("✨ Gerar Minuta com Inteligência Artificial"):
                    with st.spinner("Redigindo rascunho de petição..."):
                        minuta_gerada = gerar_minuta_com_gemini(
                            proc_escolhido, dado_proc["resumo"]
                        )
                        st.markdown("### Rascunho Gerado:")
                        st.text_area(
                            "Edite ou copie o texto abaixo:",
                            value=minuta_gerada,
                            height=300,
                        )
            else:
                st.info("Cadastre um processo primeiro para gerar minutas.")

        with aba_cnj:
            st.subheader("🔍 Consulta Oficial de Andamentos (DataJud - CNJ)")
            st.markdown("Consulte metadados e movimentações diretamente da base nacional unificada do Poder Judiciário.")

            tribunais_datajud = {
                "Tribunal de Justiça de São Paulo (TJSP)": "api_publica_tjsp",
                "Tribunal de Justiça de Minas Gerais (TJMG)": "api_publica_tjmg",
                "Tribunal de Justiça do Rio de Janeiro (TJRJ)": "api_publica_tjrj",
                "Tribunal de Justiça do Rio Grande do Sul (TJRS)": "api_publica_tjrs",
                "Tribunal de Justiça do Paraná (TJPR)": "api_publica_tjpr",
                "Tribunal de Justiça de Santa Catarina (TJSC)": "api_publica_tjsc",
                "Tribunal de Justiça do Distrito Federal (TJDFT)": "api_publica_tjdft",
                "Tribunal de Justiça de Goiás (TJGO)": "api_publica_tjgo",
            }

            col_t1, col_t2 = st.columns([1, 1])
            with col_t1:
                tribunal_escolhido = st.selectbox("Selecione o Tribunal:", list(tribunais_datajud.keys()))
            with col_t2:
                cnj_busca = st.text_input("Número do Processo (CNJ):", placeholder="Ex: 10091315220248260224")

            if st.button("Consultar Base Oficial do DataJud"):
                if cnj_busca.strip():
                    with st.spinner("Buscando dados oficiais no DataJud (CNJ)..."):
                        alias_tribunal = tribunais_datajud[tribunal_escolhido]
                        url_dj = f"https://api-publica.datajud.cnj.jus.br/{alias_tribunal}/_search"
                        
                        api_key_datajud = "APIKey cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
                        numero_limpo = "".join(filter(str.isdigit, cnj_busca))
                        
                        payload_dj = {
                            "query": {
                                "match": {
                                    "numeroProcesso": numero_limpo
                                }
                            }
                        }
                        
                        headers_dj = {
                            "Authorization": api_key_datajud,
                            "Content-Type": "application/json"
                        }
                        
                        try:
                            resp = requests.post(url_dj, json=payload_dj, headers=headers_dj)
                            if resp.status_code == 200:
                                dados = resp.json()
                                hits = dados.get("hits", {}).get("hits", [])
                                
                                if hits:
                                    processo_info = hits[0]["_source"]
                                    st.success("Processo encontrado na base oficial do CNJ!")
                                    
                                    st.markdown(f"**📁 Processo:** {processo_info.get('numeroProcesso')}")
                                    st.markdown(f"**🏛️ Tribunal:** {processo_info.get('tribunal')}")
                                    st.markdown(f"**⚖️ Classe:** {processo_info.get('classe', {}).get('nome', 'Não informada')}")
                                    
                                    data_ajuizamento = processo_info.get('dataAjuizamento', '')
                                    if data_ajuizamento:
                                        st.markdown(f"**📅 Data de Ajuizamento:** {data_ajuizamento[:10]}")
                                    
                                    st.markdown("### 📋 Histórico de Movimentações:")
                                    movimentacoes = processo_info.get("movimentos", [])
                                    if movimentacoes:
                                        for mov in movimentacoes[:10]:
                                            data_mov = mov.get("dataHora", "")[:10]
                                            nome_mov = mov.get("nome", "Movimentação")
                                            st.write(f"- **{data_mov}**: {nome_mov}")
                                    else:
                                        st.info("Nenhuma movimentação detalhada encontrada para este registro.")
                                else:
                                    st.warning("⚠️ Nenhum processo encontrado com este número no tribunal selecionado.")
                            else:
                                st.error(f"Erro ao consultar a API do DataJud (Código HTTP: {resp.status_code})")
                        except Exception as e:
                            st.error(f"Erro de conexão com os servidores do DataJud: {e}")
                else:
                    st.warning("Insira um número CNJ válido.")
        
        with aba_advogados:
            st.subheader("👥 Cadastro da Equipe Jurídica")
            col_form, col_lista = st.columns([1, 1.5])
            with col_form:
                with st.form("form_advogado"):
                    nome_adv = st.text_input("Nome Completo")
                    oab_adv = st.text_input("OAB (Ex: MG 123.456)")
                    email_adv = st.text_input(
                        "E-mail de Notificação", value=usuario_atual.email
                    )
                    whatsapp_adv = st.text_input("WhatsApp (Ex: 5531999996982)")
                    if st.form_submit_button("Salvar Advogado"):
                        if nome_adv and oab_adv and email_adv and whatsapp_adv:
                            try:
                                dados_adv = {
                                    "user_id": usuario_atual.id,
                                    "nome": nome_adv,
                                    "oab": oab_adv,
                                    "email": email_adv,
                                    "whatsapp": whatsapp_adv,
                                }
                                supabase.table("advogados").insert(dados_adv).execute()
                                st.success("Salvo com sucesso!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao salvar: {e}")
                        else:
                            st.error("Preencha todos os campos.")
            with col_lista:
                try:
                    resp_adv = supabase.table("advogados").select("*").execute()
                    df_adv = (
                        pd.DataFrame(resp_adv.data) if resp_adv.data else pd.DataFrame()
                    )
                    if not df_adv.empty:
                        st.dataframe(df_adv, use_container_width=True, hide_index=True)
                except Exception:
                    pass
    else:
        st.warning(
            f"🔒 **Período de Teste Expirado para a conta:**"
            f" `{usuario_atual.email}`\n\nSeu período gratuito de 30 dias chegou ao"
            " fim. Para continuar utilizando o PrazoGuard, escolha o seu plano"
            " abaixo:"
        )
        col_pay1, col_pay2, col_pay3 = st.columns([1, 2, 1])
        with col_pay2:
            plano_selecionado = st.radio(
                "Selecione o plano:",
                ["Plano Individual (R$ 97 / mês)", "Plano Escritório (R$ 197 / mês)"],
            )
            if st.button(
                "🚀 Assinar e Liberar Acesso Definitivo", use_container_width=True
            ):
                price_id = (
                    "price_cole_aqui_o_id_do_individual_97"
                    if "Individual" in plano_selecionado
                    else "price_cole_aqui_o_id_do_escritorio_197"
                )
                try:
                    checkout_session = stripe.checkout.Session.create(
                        payment_method_types=["card"],
                        line_items=[{"price": price_id, "quantity": 1}],
                        mode="subscription",
                        success_url="https://www.prazoguard.com.br/?sucesso=true",
                        cancel_url="https://www.prazoguard.com.br/?cancelado=true",
                        customer_email=usuario_atual.email,
                    )
                    st.markdown(
                        f'<meta http-equiv="refresh" content="0;url={checkout_session.url}">',
                        unsafe_allow_html=True,
                    )
                except Exception as e:
                    st.error(f"Erro: {e}")