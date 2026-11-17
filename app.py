import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime
import uuid
import os
import re
import json
from dotenv import load_dotenv
from pypdf import PdfReader
from google import genai
import database as db

# Carrega variáveis de ambiente (Chave da API do Gemini)
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

# Inicializa o cliente do Gemini se a chave existir
client = None
if api_key:
    try:
        client = genai.Client(api_key=api_key)
    except Exception:
        client = None

# Inicializa e atualiza o banco de dados
db.criar_tabelas()
db.inserir_dados_iniciais()

# Garante que a pasta de uploads físicos existe
DIRETORIO_UPLOADS = "uploads"
if not os.path.exists(DIRETORIO_UPLOADS):
    os.makedirs(DIRETORIO_UPLOADS)

st.set_page_config(page_title="Gestão Financeira PJ | Prestadores de Serviços", layout="wide")

SIMBOLOS = {"BRL": "R$", "EUR": "€", "USD": "US$"}

def formatar_moeda(valor, simbolo):
    """Formata números no padrão brasileiro/europeu: R$ 1.250,50"""
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{simbolo} {texto}"

def formatar_data_br(data_iso):
    """Converte 'YYYY-MM-DD' para 'DD/MM/YYYY' para exibição."""
    if not data_iso or pd.isna(data_iso):
        return ""
    try:
        return datetime.strptime(str(data_iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(data_iso)

def adicionar_meses(data_base, meses):
    """Soma meses exatos a uma data, ajustando o dia se o mês for mais curto."""
    ano = data_base.year + (data_base.month + meses - 1) // 12
    mes = (data_base.month + meses - 1) % 12 + 1
    dias_no_mes = [
        31,
        29 if (ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    ][mes - 1]
    dia = min(data_base.day, dias_no_mes)
    return date(ano, mes, dia)

# --- GARANTIR COLUNA DE CLIENTE NO BANCO ---
def garantir_coluna_cliente():
    conn = db.conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT cliente FROM movimentacoes LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE movimentacoes ADD COLUMN cliente TEXT DEFAULT ''")
        conn.commit()
    conn.close()

garantir_coluna_cliente()

# --- BARRA LATERAL: PERFIS ---
st.sidebar.title("Perfis PJ & Negócios")

conn = db.conectar()
df_perfis = pd.read_sql_query("SELECT * FROM perfis", conn)
conn.close()

opcoes_perfis = {
    f"{row['nome']} ({row['tipo']} - {row['moeda']})": row['id']
    for _, row in df_perfis.iterrows()
}

perfil_selecionado_label = st.sidebar.selectbox("Perfil Ativo:", list(opcoes_perfis.keys()))
perfil_id = opcoes_perfis[perfil_selecionado_label]

perfil_ativo = df_perfis[df_perfis["id"] == perfil_id].iloc[0]
moeda = perfil_ativo["moeda"]
simbolo = SIMBOLOS[moeda]

st.sidebar.divider()

# --- GERENCIAR / EDITAR OU EXCLUIR PERFIL ATIVO ---
with st.sidebar.expander("Gerenciar Perfil Ativo"):
    with st.form("form_editar_perfil"):
        ed_nome = st.text_input("Nome da Empresa", value=perfil_ativo["nome"])
        ed_tipo = st.selectbox("Tipo", ["PJ", "PF"], index=0 if perfil_ativo["tipo"] == "PJ" else 1)
        ed_moeda = st.selectbox("Moeda", ["BRL", "EUR", "USD"], index=["BRL", "EUR", "USD"].index(perfil_ativo["moeda"]))
        ed_doc = st.text_input("CNPJ / NIF / CPF", value=perfil_ativo["documento"] or "")
        
        btn_salvar_perfil = st.form_submit_button("Salvar Alterações")
        if btn_salvar_perfil and ed_nome:
            conn = db.conectar()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE perfis SET nome = ?, tipo = ?, moeda = ?, documento = ? WHERE id = ?",
                (ed_nome, ed_tipo, ed_moeda, ed_doc, int(perfil_id))
            )
            conn.commit()
            conn.close()
            st.success("Perfil atualizado com sucesso.")
            st.rerun()

    st.markdown("---")
    if len(df_perfis) > 1:
        if st.button("🗑️ Excluir Perfil Atual", type="primary"):
            conn = db.conectar()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM movimentacoes WHERE perfil_id = ?", (int(perfil_id),))
            cursor.execute("DELETE FROM contas WHERE perfil_id = ?", (int(perfil_id),))
            cursor.execute("DELETE FROM documentos WHERE perfil_id = ?", (int(perfil_id),))
            cursor.execute("DELETE FROM perfis WHERE id = ?", (int(perfil_id),))
            conn.commit()
            conn.close()
            st.warning("Perfil e todos os seus dados foram excluídos.")
            st.rerun()
    else:
        st.caption("⚠️ Você não pode excluir o único perfil restante no sistema.")

st.sidebar.divider()

with st.sidebar.expander("Novo Perfil PJ / Empresa"):
    with st.form("form_novo_perfil", clear_on_submit=True):
        novo_nome = st.text_input("Nome da Empresa (ex: Consultoria LTDA)")
        novo_tipo = st.selectbox("Tipo", ["PJ", "PF"])
        nova_moeda = st.selectbox("Moeda", ["BRL", "EUR", "USD"])
        novo_doc = st.text_input("CNPJ / NIF / CPF")
        submitted = st.form_submit_button("Criar Perfil")

        if submitted and novo_nome:
            conn = db.conectar()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO perfis (nome, tipo, moeda, documento) VALUES (?, ?, ?, ?)",
                (novo_nome, novo_tipo, nova_moeda, novo_doc)
            )
            novo_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO contas (perfil_id, nome, tipo, saldo_inicial) VALUES (?, ?, ?, ?)",
                (novo_id, f"Conta Principal {nova_moeda}", "Conta Corrente", 0.0)
            )
            conn.commit()
            conn.close()
            st.success("Perfil criado com sucesso.")
            st.rerun()

# --- CABEÇALHO ---
st.title(f"{perfil_ativo['nome']}")
st.caption(f"Gestão Financeira Corporativa | Moeda Base: **{moeda} ({simbolo})** | CNPJ/Documento: {perfil_ativo['documento'] or 'Não informado'}")

# --- CARREGAR DADOS DO PERFIL ATIVO COM SEGURANÇA BLINDADA ---
conn = db.conectar()
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        perfil_id INTEGER,
        titulo TEXT NOT NULL,
        tipo_doc TEXT NOT NULL,
        nome_arquivo TEXT NOT NULL,
        data_envio TEXT NOT NULL,
        FOREIGN KEY (perfil_id) REFERENCES perfis(id)
    )
""")
conn.commit()

df_contas = pd.read_sql_query(f"SELECT * FROM contas WHERE perfil_id = {perfil_id}", conn)
df_mov = pd.read_sql_query(f"""
    SELECT m.*, c.nome as conta_nome
    FROM movimentacoes m
    JOIN contas c ON m.conta_id = c.id
    WHERE m.perfil_id = {perfil_id}
    ORDER BY m.data_vencimento ASC, m.id ASC
""", conn)
df_docs = pd.read_sql_query(f"SELECT * FROM documentos WHERE perfil_id = {perfil_id} ORDER BY id DESC", conn)
conn.close()

if "cliente" not in df_mov.columns:
    df_mov["cliente"] = ""

# --- CÁLCULOS DOS 4 INDICADORES ---
saldo_inicial_total = df_contas["saldo_inicial"].sum() if not df_contas.empty else 0.0

if not df_mov.empty:
    receitas_efetivadas = df_mov[(df_mov["tipo"] == "RECEITA") & (df_mov["status"] == "EFETIVADO")]["valor"].sum()
    despesas_efetivadas = df_mov[(df_mov["tipo"] == "DESPESA") & (df_mov["status"] == "EFETIVADO")]["valor"].sum()
    a_receber = df_mov[(df_mov["tipo"] == "RECEITA") & (df_mov["status"] == "PENDENTE")]["valor"].sum()
    a_pagar = df_mov[(df_mov["tipo"] == "DESPESA") & (df_mov["status"] == "PENDENTE")]["valor"].sum()
else:
    receitas_efetivadas = despesas_efetivadas = a_receber = a_pagar = 0.0

quanto_tenho = saldo_inicial_total + receitas_efetivadas - despesas_efetivadas
saldo_projetado = quanto_tenho + a_receber - a_pagar

# --- ABAS DO SISTEMA ---
aba_geral, aba_lancar, aba_ia, aba_relatorios, aba_docs, aba_contas = st.tabs([
    "Visão Geral & Lançamentos",
    "Novo Lançamento",
    "🤖 IA & Importação Smart",
    "DRE & Relatórios",
    "Documentos & Anexos",
    "Contas Bancárias"
])

# ==========================================
# ABA 1: VISÃO GERAL, FILTRO E EDIÇÃO
# ==========================================
with aba_geral:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Caixa Atual (Disponível)", formatar_moeda(quanto_tenho, simbolo))
    col2.metric("A Receber (Pendente)", formatar_moeda(a_receber, simbolo))
    col3.metric("A Pagar (Pendente)", formatar_moeda(a_pagar, simbolo))
    col4.metric(
        "Caixa Projetado",
        formatar_moeda(saldo_projetado, simbolo),
        delta=formatar_moeda(a_receber - a_pagar, simbolo)
    )

    st.divider()

    # --- PAINEL DE CONTROLE DE VENCIMENTOS E ALERTAS (NOVO) ---
    st.subheader(" Painel de Vencimentos ")
    
    if not df_mov.empty:
        hoje_str = str(date.today())
        
        # Filtra pendentes
        df_pend = df_mov[df_mov["status"] == "PENDENTE"].copy()
        
        if not df_pend.empty:
            vencidos = df_pend[df_pend["data_vencimento"] < hoje_str]
            vencem_hoje = df_pend[df_pend["data_vencimento"] == hoje_str]
            
            # Alertas visuais em colunas
            ac1, ac2 = st.columns(2)
            
            with ac1:
                total_vencido = vencidos["valor"].sum() if not vencidos.empty else 0.0
                st.markdown(f"### ⚠️ Vencidos / Inadimplentes: `{formatar_moeda(total_vencido, simbolo)}`")
                if vencidos.empty:
                    st.success("Nenhum lançamento vencido em atraso!")
                else:
                    for _, v_item in vencidos.iterrows():
                        tipo_leg = "A Receber" if v_item["tipo"] == "RECEITA" else "A Pagar"
                        cli_str = f" ({v_item['cliente']})" if v_item.get("cliente") else ""
                        st.error(f"**{v_item['descricao']}**{cli_str} | Venc.: **{formatar_data_br(v_item['data_vencimento'])}** | **{formatar_moeda(v_item['valor'], simbolo)}** [{tipo_leg}]")

            with ac2:
                total_hoje = vencem_hoje["valor"].sum() if not vencem_hoje.empty else 0.0
                st.markdown(f"###  Vencem Hoje: `{formatar_moeda(total_hoje, simbolo)}`")
                if vencem_hoje.empty:
                    st.info("Nenhum vencimento programado para hoje.")
                else:
                    for _, h_item in vencem_hoje.iterrows():
                        tipo_leg = "A Receber" if h_item["tipo"] == "RECEITA" else "A Pagar"
                        cli_str = f" ({h_item['cliente']})" if h_item.get("cliente") else ""
                        st.warning(f"**{h_item['descricao']}**{cli_str} | **{formatar_moeda(h_item['valor'], simbolo)}** [{tipo_leg}]")
        else:
            st.info("Nenhum lançamento pendente no momento.")
    else:
        st.info("Cadastre lançamentos para visualizar os alertas de vencimento.")

    st.divider()

    st.subheader("Controle e Histórico")
    
    if not df_mov.empty:
        df_mov["mes_iso"] = df_mov["data_vencimento"].str.slice(0, 7)
        lista_meses_disponiveis = sorted(df_mov["mes_iso"].unique(), reverse=True)
        
        opcoes_filtro = ["Todos os Períodos"] + [f"{m.split('-')[1]}/{m.split('-')[0]}" for m in lista_meses_disponiveis]
        filtro_escolhido = st.selectbox("Filtrar por Período:", opcoes_filtro)
        
        if filtro_escolhido != "Todos os Períodos":
            mes_num, ano_num = filtro_escolhido.split("/")
            mes_alvo = f"{ano_num}-{mes_num}"
            df_mov_filtrado = df_mov[df_mov["mes_iso"] == mes_alvo]
        else:
            df_mov_filtrado = df_mov.copy()
    else:
        df_mov_filtrado = pd.DataFrame()

    st.markdown("#### Contas a Pagar e Receber (Pendentes)")
    df_pendentes = df_mov_filtrado[df_mov_filtrado["status"] == "PENDENTE"] if not df_mov_filtrado.empty else pd.DataFrame()

    if df_pendentes.empty:
        st.info("Nenhum registro pendente para o período selecionado.")
    else:
        for _, item in df_pendentes.iterrows():
            c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 1.5])
            status_txt = "Receber" if item["tipo"] == "RECEITA" else "Pagar"
            cli_txt = f" | Cliente: {item['cliente']}" if item.get('cliente') else ""
            c1.write(f"**{item['descricao']}** ({item['categoria']}){cli_txt}")
            c2.write(f"{status_txt} | {item['conta_nome']}")
            c3.write(f"Venc.: **{formatar_data_br(item['data_vencimento'])}**")
            c4.write(f"**{formatar_moeda(item['valor'], simbolo)}**")
            if c5.button("Baixar", key=f"baixar_{item['id']}"):
                conn = db.conectar()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE movimentacoes SET status = 'EFETIVADO', data_pagamento = ? WHERE id = ?",
                    (str(date.today()), item["id"])
                )
                conn.commit()
                conn.close()
                st.rerun()

    st.divider()

    st.markdown("#### Histórico de Lançamentos")
    if df_mov_filtrado.empty:
        st.write("Nenhum lançamento encontrado para o período.")
    else:
        df_exibir = df_mov_filtrado[["id", "data_vencimento", "tipo", "descricao", "cliente", "categoria", "conta_nome", "status", "valor"]].copy()
        df_exibir["data_vencimento"] = df_exibir["data_vencimento"].apply(formatar_data_br)
        df_exibir["valor"] = df_exibir["valor"].apply(lambda x: formatar_moeda(x, simbolo))
        df_exibir.columns = ["ID", "Data", "Tipo", "Descrição", "Cliente / Tomador", "Categoria", "Conta", "Status", "Valor"]
        st.dataframe(df_exibir, use_container_width=True, hide_index=True)

        st.divider()

        with st.expander("Editar ou Excluir Lançamento"):
            opcoes_edicao = {
                f"ID #{row['id']} | {formatar_data_br(row['data_vencimento'])} | {row['descricao']} ({row['status']}) - {formatar_moeda(row['valor'], simbolo)}": row['id']
                for _, row in df_mov_filtrado.iterrows()
            }
            if not opcoes_edicao:
                st.write("Nenhum item disponível para edição no filtro atual.")
            else:
                item_selecionado_label = st.selectbox("Selecione o registro:", list(opcoes_edicao.keys()))
                id_edit = opcoes_edicao[item_selecionado_label]
                reg = df_mov[df_mov["id"] == id_edit].iloc[0]

                cats_pj = [
                    "Honorários Contratuais/Sucumbências",
                    "Consultoria/Assessoria",
                    "Impostos (DAS/ISS/IR)",
                    "Outras Receitas",
                    "Outras Despesas"
                ]
                if reg["categoria"] not in cats_pj:
                    cats_pj.append(reg["categoria"])

                eh_serie = pd.notna(reg["grupo_id"]) and bool(reg["grupo_id"])

                converter_parcelado = False
                qtd_novas_parcelas = 2
                if not eh_serie:
                    converter_parcelado = st.checkbox("Converter este lançamento à vista em A PRAZO (Parcelado)")
                    if converter_parcelado:
                        qtd_novas_parcelas = st.number_input("Dividir em quantas parcelas?", min_value=2, max_value=120, value=2, step=1)

                with st.form("form_editar_mov"):
                    ec1, ec2, ec3 = st.columns(3)
                    nova_desc = ec1.text_input("Descrição:", value=reg["descricao"])
                    novo_cliente = ec2.text_input("Cliente / Tomador:", value=reg.get("cliente", ""))
                    novo_valor = ec3.number_input(f"Valor ({simbolo}):", value=max(0.0, float(reg["valor"])), min_value=0.0, step=10.0, format="%.2f")

                    ec4, ec5, ec6, ec7 = st.columns(4)
                    novo_status = ec4.selectbox(
                        "Status:",
                        ["PENDENTE", "EFETIVADO"],
                        index=0 if reg["status"] == "PENDENTE" else 1
                    )
                    novo_tipo_mov = ec5.selectbox(
                        "Tipo:",
                        ["RECEITA", "DESPESA"],
                        index=0 if reg["tipo"] == "RECEITA" else 1
                    )
                    nova_cat = ec6.selectbox("Categoria:", cats_pj, index=cats_pj.index(reg["categoria"]))
                    nova_data = ec7.date_input(
                        "Data:",
                        value=datetime.strptime(reg["data_vencimento"], "%Y-%m-%d").date(),
                        format="DD/MM/YYYY"
                    )

                    modo_edicao_serie = "Apenas este lançamento"
                    if eh_serie:
                        modo_edicao_serie = st.radio(
                            "Este lançamento faz parte de um contrato parcelado. Como deseja aplicar?",
                            [
                                "Apenas este lançamento",
                                "Repetir este valor em TODAS as parcelas",
                                "Dividir este valor TOTAL entre todas as parcelas"
                            ]
                        )

                    btn_salvar_edicao = st.form_submit_button("Salvar Alterações")

                    if btn_salvar_edicao and nova_desc:
                        conn = db.conectar()
                        cursor = conn.cursor()
                        data_pag = str(nova_data) if novo_status == "EFETIVADO" else None

                        if not eh_serie and converter_parcelado:
                            novo_grupo = str(uuid.uuid4())
                            valor_parcela = round(novo_valor / int(qtd_novas_parcelas), 2)

                            cursor.execute("""
                                UPDATE movimentacoes
                                SET descricao = ?, cliente = ?, valor = ?, status = ?, tipo = ?, categoria = ?, data_vencimento = ?, data_pagamento = ?, grupo_id = ?
                                WHERE id = ?
                            """, (
                                f"{nova_desc} (1/{int(qtd_novas_parcelas)})",
                                novo_cliente,
                                valor_parcela,
                                novo_status,
                                novo_tipo_mov,
                                nova_cat,
                                str(nova_data),
                                data_pag,
                                novo_grupo,
                                id_edit
                            ))

                            for i in range(1, int(qtd_novas_parcelas)):
                                data_prox = adicionar_meses(nova_data, i)
                                cursor.execute("""
                                    INSERT INTO movimentacoes
                                    (perfil_id, conta_id, descricao, cliente, categoria, tipo, status, valor, data_vencimento, data_pagamento, grupo_id)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    int(perfil_id),
                                    int(reg["conta_id"]),
                                    f"{nova_desc} ({i + 1}/{int(qtd_novas_parcelas)})",
                                    novo_cliente,
                                    nova_cat,
                                    novo_tipo_mov,
                                    "PENDENTE",
                                    valor_parcela,
                                    str(data_prox),
                                    None,
                                    novo_grupo
                                ))

                        elif modo_edicao_serie == "Apenas este lançamento":
                            cursor.execute("""
                                UPDATE movimentacoes
                                SET descricao = ?, cliente = ?, valor = ?, status = ?, tipo = ?, categoria = ?, data_vencimento = ?, data_pagamento = ?
                                WHERE id = ?
                            """, (nova_desc, novo_cliente, novo_valor, novo_status, novo_tipo_mov, nova_cat, str(nova_data), data_pag, id_edit))

                        elif modo_edicao_serie == "Repetir este valor em TODAS as parcelas":
                            cursor.execute("""
                                UPDATE movimentacoes
                                SET descricao = ?, cliente = ?, status = ?, data_vencimento = ?, data_pagamento = ?
                                WHERE id = ?
                            """, (nova_desc, novo_cliente, novo_status, str(nova_data), data_pag, id_edit))
                            cursor.execute("""
                                UPDATE movimentacoes
                                SET valor = ?, tipo = ?, categoria = ?, cliente = ?
                                WHERE grupo_id = ?
                            """, (novo_valor, novo_tipo_mov, nova_cat, novo_cliente, reg["grupo_id"]))

                        elif modo_edicao_serie == "Dividir este valor TOTAL entre todas as parcelas":
                            cursor.execute("SELECT COUNT(*) FROM movimentacoes WHERE grupo_id = ?", (reg["grupo_id"],))
                            total_parcelas = cursor.fetchone()[0]
                            valor_dividido = round(novo_valor / total_parcelas, 2)

                            cursor.execute("""
                                UPDATE movimentacoes
                                SET descricao = ?, cliente = ?, status = ?, data_vencimento = ?, data_pagamento = ?
                                WHERE id = ?
                            """, (nova_desc, novo_cliente, novo_status, str(nova_data), data_pag, id_edit))
                            cursor.execute("""
                                UPDATE movimentacoes
                                SET valor = ?, tipo = ?, categoria = ?, cliente = ?
                                WHERE grupo_id = ?
                            """, (valor_dividido, novo_tipo_mov, nova_cat, novo_cliente, reg["grupo_id"]))

                        conn.commit()
                        conn.close()
                        st.success("Lançamento(s) atualizado(s) com sucesso.")
                        st.rerun()

                st.markdown("**Zona de Exclusão:**")
                if eh_serie:
                    col_del1, col_del2, col_del3 = st.columns(3)

                    if col_del1.button("Excluir parcela e recalcular"):
                        conn = db.conectar()
                        cursor = conn.cursor()

                        cursor.execute("SELECT SUM(valor) FROM movimentacoes WHERE grupo_id = ?", (reg["grupo_id"],))
                        soma_total_serie = cursor.fetchone()[0] or 0.0

                        cursor.execute("DELETE FROM movimentacoes WHERE id = ?", (id_edit,))

                        cursor.execute(
                            "SELECT id, descricao FROM movimentacoes WHERE grupo_id = ? ORDER BY data_vencimento ASC, id ASC",
                            (reg["grupo_id"],)
                        )
                        restantes = cursor.fetchall()

                        if restantes:
                            qtd_rest = len(restantes)
                            novo_val_parc = round(soma_total_serie / qtd_rest, 2)
                            novo_grupo_rest = reg["grupo_id"] if qtd_rest > 1 else None

                            for idx, (r_id, r_desc) in enumerate(restantes):
                                nome_base = re.sub(r"\s*\((?:Mês\s*)?\d+/\d+\)$", "", r_desc).strip()
                                if qtd_rest > 1:
                                    nova_desc_parc = f"{nome_base} ({idx + 1}/{qtd_rest})"
                                else:
                                    nova_desc_parc = nome_base

                                cursor.execute(
                                    "UPDATE movimentacoes SET valor = ?, descricao = ?, grupo_id = ? WHERE id = ?",
                                    (novo_val_parc, nova_desc_parc, novo_grupo_rest, r_id)
                                )

                        conn.commit()
                        conn.close()
                        st.success("Parcela excluída e valor redistribuído.")
                        st.rerun()

                    if col_del2.button("Excluir apenas esta"):
                        conn = db.conectar()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM movimentacoes WHERE id = ?", (id_edit,))
                        conn.commit()
                        conn.close()
                        st.warning("Lançamento excluído.")
                        st.rerun()

                    if col_del3.button("Excluir contrato inteiro", type="primary"):
                        conn = db.conectar()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM movimentacoes WHERE grupo_id = ?", (reg["grupo_id"],))
                        conn.commit()
                        conn.close()
                        st.warning("Contrato excluído.")
                        st.rerun()
                else:
                    if st.button("Excluir registro", type="secondary"):
                        conn = db.conectar()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM movimentacoes WHERE id = ?", (id_edit,))
                        conn.commit()
                        conn.close()
                        st.warning("Registro excluído.")
                        st.rerun()

# ==========================================
# ABA 2: NOVO LANÇAMENTO
# ==========================================
with aba_lancar:
    st.subheader("Novo Lançamento / Contrato")

    if df_contas.empty:
        st.warning("Cadastre uma conta bancária na aba Contas Bancárias antes de registrar lançamentos.")
    else:
        categorias_pj = [
            "Honorários Contratuais/Sucumbências",
            "Consultoria/Assessoria",
            "Impostos (DAS/ISS/IR)",
            "Outras Receitas",
            "Outras Despesas"
        ]

        condicao_pagamento = st.radio(
            "Condição:",
            ["À vista (Único)", "A prazo (Parcelado / Contrato Dividido)"],
            horizontal=True
        )

        with st.form("form_lancamento", clear_on_submit=True):
            c1, c2 = st.columns(2)
            tipo_mov = c1.selectbox("Tipo:", ["RECEITA", "DESPESA"])
            status_inicial = c2.selectbox(
                "Situação inicial:",
                ["PENDENTE (A pagar / receber)", "EFETIVADO (Já pago / recebido)"]
            )

            c3, c4, c5 = st.columns(3)
            descricao = c3.text_input("Descrição / Objeto (ex: Projeto X, Mensalidade)")
            cliente = c4.text_input("Cliente / Tomador (Opcional):")

            if "A prazo" in condicao_pagamento:
                valor = c5.number_input(f"Valor TOTAL ({simbolo}):", min_value=0.01, step=50.0, format="%.2f")
            else:
                valor = c5.number_input(f"Valor ({simbolo}):", min_value=0.01, step=50.0, format="%.2f")

            c6, c7, c8 = st.columns(3)
            categoria = c6.selectbox("Categoria:", categorias_pj)

            mapa_contas = {row["nome"]: row["id"] for _, row in df_contas.iterrows()}
            conta_escolhida = c7.selectbox("Conta Bancária:", list(mapa_contas.keys()))
            data_venc = c8.date_input("Data de Vencimento:", value=date.today(), format="DD/MM/YYYY")

            qtd_parcelas = 1
            if "A prazo" in condicao_pagamento:
                qtd_parcelas = st.number_input("Número de Parcelas:", min_value=2, max_value=120, value=3, step=1)

            salvar_mov = st.form_submit_button("Salvar Registro")

            if salvar_mov:
                if not descricao:
                    st.error("Preencha a descrição.")
                else:
                    conn = db.conectar()
                    cursor = conn.cursor()

                    grupo_id = str(uuid.uuid4()) if qtd_parcelas > 1 else None
                    primeiro_status = "EFETIVADO" if "EFETIVADO" in status_inicial else "PENDENTE"

                    for i in range(int(qtd_parcelas)):
                        data_parcela = adicionar_meses(data_venc, i)
                        
                        if i == 0:
                            status_atual = primeiro_status
                            data_pag_atual = str(data_parcela) if status_atual == "EFETIVADO" else None
                        else:
                            status_atual = "PENDENTE"
                            data_pag_atual = None

                        if "A prazo" in condicao_pagamento:
                            valor_parcela = round(valor / qtd_parcelas, 2)
                            desc_final = f"{descricao} ({i + 1}/{int(qtd_parcelas)})"
                        else:
                            valor_parcela = valor
                            desc_final = descricao

                        cursor.execute("""
                            INSERT INTO movimentacoes
                            (perfil_id, conta_id, descricao, cliente, categoria, tipo, status, valor, data_vencimento, data_pagamento, grupo_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            int(perfil_id),
                            int(mapa_contas[conta_escolhida]),
                            desc_final,
                            cliente,
                            categoria,
                            tipo_mov,
                            status_atual,
                            valor_parcela,
                            str(data_parcela),
                            data_pag_atual,
                            grupo_id
                        ))

                    conn.commit()
                    conn.close()
                    st.success("Registro salvo com sucesso.")
                    st.rerun()

# ==========================================
# ABA 3: IA & IMPORTAÇÃO SMART
# ==========================================
with aba_ia:
    st.subheader(" Leitura Inteligente de Notas Fiscais e Boletos (IA)")
    st.caption("Envie o PDF da nota fiscal ou fatura. O Gemini vai ler o documento, preencher os dados e arquivar o PDF automaticamente na aba de Documentos.")

    if not client:
        st.error("⚠️ Chave da API do Gemini (`GEMINI_API_KEY`) não configurada ou inválida no arquivo `.env`.")
    elif df_contas.empty:
        st.warning("Cadastre uma conta bancária na aba Contas Bancárias antes de importar lançamentos.")
    else:
        pdf_ia = st.file_uploader("Arraste ou selecione a Nota Fiscal / Boleto em PDF:", type=["pdf"], key="upload_ia")

        if pdf_ia is not None:
            if st.button("✨ Ler Documento com IA"):
                with st.spinner("A Inteligência Artificial está analisando o documento..."):
                    try:
                        leitor = PdfReader(pdf_ia)
                        texto_pdf = ""
                        for pagina in leitor.pages:
                            t = pagina.extract_text()
                            if t:
                                texto_pdf += t + "\n"

                        prompt = f"""
                        Analise o texto abaixo extraído de uma Nota Fiscal, Fatura ou Boleto e extraia as informações financeiras em formato JSON estrito (sem markdown, apenas chaves e valores):
                        - "descricao": Resumo claro do serviço ou produto (string)
                        - "cliente": Nome do tomador, cliente ou empresa emissora/pagadora (string)
                        - "valor": Valor numérico total da nota/boleto (apenas número float, ex: 1500.50)
                        - "data_vencimento": Data de vencimento ou emissão no formato YYYY-MM-DD (string, se não achar coloque a data de hoje)
                        - "tipo": "RECEITA" se for ganho/honorário para esta empresa, ou "DESPESA" se for boleto/imposto a pagar (string)

                        Texto do documento:
                        {texto_pdf[:4000]}
                        """

                        resposta = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=prompt,
                        )

                        texto_limpo = resposta.text.replace("```json", "").replace("```", "").strip()
                        dados_extraidos = json.loads(texto_limpo)

                        st.session_state["ia_descricao"] = dados_extraidos.get("descricao", "")
                        st.session_state["ia_cliente"] = dados_extraidos.get("cliente", "")
                        st.session_state["ia_valor"] = float(dados_extraidos.get("valor", 0.0))
                        
                        try:
                            st.session_state["ia_data"] = datetime.strptime(dados_extraidos.get("data_vencimento", str(date.today())), "%Y-%m-%d").date()
                        except Exception:
                            st.session_state["ia_data"] = date.today()

                        st.session_state["ia_tipo"] = dados_extraidos.get("tipo", "RECEITA")
                        st.session_state["ia_arquivo_bytes"] = pdf_ia.getvalue()
                        st.session_state["ia_arquivo_nome"] = pdf_ia.name
                        st.success("Leitura realizada com sucesso! Confira e ajuste os dados abaixo antes de salvar.")

                    except Exception as e:
                        st.error(f"Erro ao processar o documento com a IA: {e}")

        if "ia_descricao" in st.session_state:
            st.divider()
            st.markdown("#### 📋 Conferência dos Dados Extraídos")

            categorias_pj = [
                "Honorários Contratuais/Sucumbências",
                "Consultoria/Assessoria",
                "Impostos (DAS/ISS/IR)",
                "Outras Receitas",
                "Outras Despesas"
            ]

            with st.form("form_confirma_ia"):
                ic1, ic2, ic3 = st.columns(3)
                f_tipo = ic1.selectbox("Tipo:", ["RECEITA", "DESPESA"], index=0 if st.session_state.get("ia_tipo") == "RECEITA" else 1)
                f_status = ic2.selectbox("Situação inicial:", ["PENDENTE (A pagar / receber)", "EFETIVADO (Já pago / recebido)"])
                f_tipo_doc = ic3.selectbox(
                    "Arquivar documento como:",
                    ["Nota Fiscal (NF-e)", "Boleto / Imposto", "Comprovante de Pagamento", "Contrato de Prestação", "Outro"],
                    index=0 if st.session_state.get("ia_tipo") == "RECEITA" else 1
                )

                ic4, ic5, ic6 = st.columns(3)
                f_desc = ic4.text_input("Descrição:", value=st.session_state.get("ia_descricao", ""))
                f_cliente = ic5.text_input("Cliente / Tomador:", value=st.session_state.get("ia_cliente", ""))
                f_valor = ic6.number_input(f"Valor ({simbolo}):", value=st.session_state.get("ia_valor", 0.0), min_value=0.01, step=10.0, format="%.2f")

                ic7, ic8, ic9 = st.columns(3)
                f_cat = ic7.selectbox("Categoria:", categorias_pj)
                mapa_contas_ia = {row["nome"]: row["id"] for _, row in df_contas.iterrows()}
                f_conta = ic8.selectbox("Conta Bancária:", list(mapa_contas_ia.keys()), key="conta_ia_sel")
                f_data = ic9.date_input("Data de Vencimento:", value=st.session_state.get("ia_data", date.today()), format="DD/MM/YYYY")

                salvar_anexo = st.checkbox("Arquivar cópia deste PDF na aba 'Documentos & Anexos'", value=True)
                btn_final_ia = st.form_submit_button("💾 Salvar Lançamento e Arquivar PDF")

                if btn_final_ia:
                    if not f_desc:
                        st.error("A descrição não pode estar vazia.")
                    else:
                        conn = db.conectar()
                        cursor = conn.cursor()
                        st_final = "EFETIVADO" if "EFETIVADO" in f_status else "PENDENTE"
                        dt_pag_final = str(f_data) if st_final == "EFETIVADO" else None

                        cursor.execute("""
                            INSERT INTO movimentacoes
                            (perfil_id, conta_id, descricao, cliente, categoria, tipo, status, valor, data_vencimento, data_pagamento, grupo_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                        """, (
                            int(perfil_id),
                            int(mapa_contas_ia[f_conta]),
                            f_desc,
                            f_cliente,
                            f_cat,
                            f_tipo,
                            st_final,
                            f_valor,
                            str(f_data),
                            dt_pag_final
                        ))

                        if salvar_anexo and "ia_arquivo_bytes" in st.session_state:
                            nome_orig = st.session_state.get("ia_arquivo_nome", "documento.pdf")
                            nome_unico = f"{uuid.uuid4()}_{nome_orig}"
                            caminho_completo = os.path.join(DIRETORIO_UPLOADS, nome_unico)

                            with open(caminho_completo, "wb") as f:
                                f.write(st.session_state["ia_arquivo_bytes"])

                            titulo_anexo = f"{f_desc} ({f_cliente})" if f_cliente else f_desc
                            cursor.execute(
                                "INSERT INTO documentos (perfil_id, titulo, tipo_doc, nome_arquivo, data_envio) VALUES (?, ?, ?, ?, ?)",
                                (int(perfil_id), titulo_anexo, f_tipo_doc, nome_unico, str(date.today()))
                            )

                        conn.commit()
                        conn.close()

                        for chave in ["ia_descricao", "ia_cliente", "ia_valor", "ia_data", "ia_tipo", "ia_arquivo_bytes", "ia_arquivo_nome"]:
                            st.session_state.pop(chave, None)

                        st.success("Lançamento salvo e PDF arquivado com sucesso!")
                        st.rerun()

# ==========================================
# ABA 4: RELATÓRIOS, CLIENTES E EXPORTAÇÃO PDF
# ==========================================
with aba_relatorios:
    st.subheader("DRE Gerencial & Faturamento")

    if df_mov.empty:
        st.info("Cadastre registros para visualizar os relatórios.")
    else:
        incluir_pendentes = st.checkbox("Incluir lançamentos futuros (Pendentes) nos relatórios", value=True)
        df_analise = df_mov.copy() if incluir_pendentes else df_mov[df_mov["status"] == "EFETIVADO"].copy()

        if df_analise.empty:
            st.warning("Sem dados para exibir.")
        else:
            total_rec = df_analise[df_analise["tipo"] == "RECEITA"]["valor"].sum()
            total_desp = df_analise[df_analise["tipo"] == "DESPESA"]["valor"].sum()
            resultado_periodo = total_rec - total_desp
            margem_lucro = ((resultado_periodo / total_rec) * 100) if total_rec > 0 else 0.0

            k1, k2, k3 = st.columns(3)
            k1.metric("Faturamento Total", formatar_moeda(total_rec, simbolo))
            k2.metric("Despesas Totais", formatar_moeda(total_desp, simbolo))
            k3.metric("Margem Líquida", f"{margem_lucro:.1f}%", delta=formatar_moeda(resultado_periodo, simbolo))

            st.divider()

            st.markdown("#### Relatório Executivo para Contador (PDF)")
            
            conteudo_pdf = f"""==================================================
RELATÓRIO FINANCEIRO EXECUTIVO - {perfil_ativo['nome'].upper()}
CNPJ/Documento: {perfil_ativo['documento'] or 'N/I'}
Moeda: {moeda} ({simbolo})
Data de Emissão: {date.today().strftime('%d/%m/%Y')}
==================================================

1. INDICADORES GERAIS:
- Faturamento Total: {formatar_moeda(total_rec, simbolo)}
- Despesas Totais: {formatar_moeda(total_desp, simbolo)}
- Resultado Líquido: {formatar_moeda(resultado_periodo, simbolo)}
- Margem Líquida: {margem_lucro:.1f}%

2. DETALHAMENTO DE LANÇAMENTOS DO PERÍODO:
"""
            for _, row in df_analise.iterrows():
                conteudo_pdf += f"[{formatar_data_br(row['data_vencimento'])}] {row['tipo']} | {row['descricao']} | Cliente: {row.get('cliente', '-')} | Cat: {row['categoria']} | Valor: {formatar_moeda(row['valor'], simbolo)} | Status: {row['status']}\n"

            conteudo_pdf += "\n==================================================\nFim do Relatório - Gerado por Sistema Corporativo"

            st.download_button(
                label="Baixar Relatório Executivo (TXT / PDF Formatado)",
                data=conteudo_pdf.encode("utf-8-sig"),
                file_name=f"Relatorio_Financeiro_{perfil_ativo['nome']}_{date.today().strftime('%Y-%m-%d')}.txt",
                mime="text/plain"
            )

            st.divider()

            st.markdown("#### Faturamento por Cliente")
            df_clientes = df_analise[(df_analise["tipo"] == "RECEITA") & (df_analise["cliente"] != "")]
            if df_clientes.empty:
                st.info("Nenhum cliente informado nas receitas.")
            else:
                df_cli_group = df_clientes.groupby("cliente")["valor"].sum().reset_index()
                df_cli_group = df_cli_group.sort_values(by="valor", ascending=False)
                df_cli_group["valor_fmt"] = df_cli_group["valor"].apply(lambda x: formatar_moeda(x, simbolo))
                df_cli_group.columns = ["Cliente / Tomador", "Valor Total", "Formatado"]
                st.dataframe(df_cli_group[["Cliente / Tomador", "Formatado"]], use_container_width=True, hide_index=True)

            st.divider()

            df_analise["mes_iso"] = df_analise["data_vencimento"].str.slice(0, 7)
            meses_ordenados = sorted(df_analise["mes_iso"].unique())

            dados_mensais = []
            patrimonio_acumulado = saldo_inicial_total

            for m_iso in meses_ordenados:
                sub = df_analise[df_analise["mes_iso"] == m_iso]
                rec_m = sub[sub["tipo"] == "RECEITA"]["valor"].sum()
                desp_m = sub[sub["tipo"] == "DESPESA"]["valor"].sum()
                lucro_m = rec_m - desp_m
                patrimonio_acumulado += lucro_m
                ano_str, mes_str = m_iso.split("-")
                mes_br = f"{mes_str}/{ano_str}"

                dados_mensais.append({
                    "Mês": mes_br,
                    "Receitas": rec_m,
                    "Despesas": desp_m,
                    "Resultado Líquido": lucro_m,
                    "Caixa Acumulado": patrimonio_acumulado
                })

            df_mensal = pd.DataFrame(dados_mensais)

            st.markdown("#### Evolução do Caixa Acumulado")
            fig_patrimonio = go.Figure()

            cores_resultado = ["#2ECC71" if v >= 0 else "#E74C3C" for v in df_mensal["Resultado Líquido"]]
            fig_patrimonio.add_trace(go.Bar(
                name="Resultado do Mês",
                x=df_mensal["Mês"],
                y=df_mensal["Resultado Líquido"],
                marker_color=cores_resultado,
                opacity=0.45
            ))

            fig_patrimonio.add_trace(go.Scatter(
                name="Caixa Acumulado",
                x=df_mensal["Mês"],
                y=df_mensal["Caixa Acumulado"],
                mode="lines+markers+text",
                text=[formatar_moeda(v, simbolo) for v in df_mensal["Caixa Acumulado"]],
                textposition="top center",
                line=dict(color="#1F77B4", width=3),
                marker=dict(size=9)
            ))

            fig_patrimonio.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Zero")
            fig_patrimonio.update_layout(xaxis_title="Mês / Ano", yaxis_title=f"Valor ({simbolo})", hovermode="x unified")
            st.plotly_chart(fig_patrimonio, use_container_width=True)

            st.divider()

            st.markdown("#### DRE Gerencial")
            df_dre_exibir = df_mensal.copy()
            for col_num in ["Receitas", "Despesas", "Resultado Líquido", "Caixa Acumulado"]:
                df_dre_exibir[col_num] = df_dre_exibir[col_num].apply(lambda x: formatar_moeda(x, simbolo))

            st.dataframe(df_dre_exibir, use_container_width=True, hide_index=True)

            csv_dados = df_mensal.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="Baixar DRE em CSV / Excel",
                data=csv_dados,
                file_name=f"DRE_Corporativo_{perfil_ativo['nome']}_{moeda}.csv",
                mime="text/csv"
            )

# ==========================================
# ABA 5: DOCUMENTOS & ANEXOS
# ==========================================
with aba_docs:
    st.subheader("Documentos, Notas Fiscais & Contratos")
    st.caption("Anexe arquivos PDF de notas fiscais, recibos, boletos ou contratos vinculados a este perfil.")

    with st.form("form_upload_doc", clear_on_submit=True):
        dc1, dc2 = st.columns(2)
        titulo_doc = dc1.text_input("Título / Nome de Identificação (ex: NF-e 102 - Consultoria)")
        tipo_doc = dc2.selectbox("Tipo de Documento:", ["Nota Fiscal (NF-e)", "Contrato de Prestação", "Comprovante de Pagamento", "Boleto / Imposto", "Outro"])
        
        arquivo_enviado = st.file_uploader("Selecione o arquivo PDF:", type=["pdf"])
        
        btn_salvar_doc = st.form_submit_button("Enviar e Salvar Documento")

        if btn_salvar_doc:
            if not titulo_doc or not arquivo_enviado:
                st.error("Preencha o título e selecione um arquivo PDF.")
            else:
                nome_unico = f"{uuid.uuid4()}_{arquivo_enviado.name}"
                caminho_completo = os.path.join(DIRETORIO_UPLOADS, nome_unico)
                
                with open(caminho_completo, "wb") as f:
                    f.write(arquivo_enviado.getbuffer())
                
                conn = db.conectar()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO documentos (perfil_id, titulo, tipo_doc, nome_arquivo, data_envio) VALUES (?, ?, ?, ?, ?)",
                    (int(perfil_id), titulo_doc, tipo_doc, nome_unico, str(date.today()))
                )
                conn.commit()
                conn.close()
                st.success("Documento enviado e salvo com sucesso.")
                st.rerun()

    st.divider()
    st.markdown("#### Documentos Armazenados")

    if df_docs.empty:
        st.info("Nenhum documento anexado para este perfil.")
    else:
        for _, doc in df_docs.iterrows():
            c_d1, c_d2, c_d3, c_d4 = st.columns([3, 2, 2, 1.5])
            c_d1.write(f"**{doc['titulo']}**")
            c_d2.write(f"Tipo: {doc['tipo_doc']}")
            c_d3.write(f"Data: {formatar_data_br(doc['data_envio'])}")
            
            caminho_arquivo = os.path.join(DIRETORIO_UPLOADS, doc['nome_arquivo'])
            
            if os.path.exists(caminho_arquivo):
                with open(caminho_arquivo, "rb") as f:
                    bytes_pdf = f.read()
                
                c_d4.download_button(
                    label="Baixar PDF",
                    data=bytes_pdf,
                    file_name=doc['nome_arquivo'].split("_", 1)[-1],
                    mime="application/pdf",
                    key=f"down_doc_{doc['id']}"
                )
            else:
                c_d4.caption("Arquivo não encontrado")

            if st.button("Excluir Documento", key=f"del_doc_{doc['id']}"):
                if os.path.exists(caminho_arquivo):
                    os.remove(caminho_arquivo)
                
                conn = db.conectar()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM documentos WHERE id = ?", (int(doc['id']),))
                conn.commit()
                conn.close()
                st.warning("Documento excluído.")
                st.rerun()
            st.divider()

# ==========================================
# ABA 6: CONTAS BANCÁRIAS
# ==========================================
with aba_contas:
    st.subheader("Contas Bancárias e Caixas")

    if df_contas.empty:
        st.info("Nenhuma conta cadastrada.")
    else:
        for _, conta in df_contas.iterrows():
            mov_conta = df_mov[(df_mov["conta_id"] == conta["id"]) & (df_mov["status"] == "EFETIVADO")] if not df_mov.empty else pd.DataFrame()
            rec_c = mov_conta[mov_conta["tipo"] == "RECEITA"]["valor"].sum() if not mov_conta.empty else 0.0
            desp_c = mov_conta[mov_conta["tipo"] == "DESPESA"]["valor"].sum() if not mov_conta.empty else 0.0
            saldo_atual_c = conta["saldo_inicial"] + rec_c - desp_c

            total_mov_conta = len(df_mov[df_mov["conta_id"] == conta["id"]]) if not df_mov.empty else 0

            col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 1.5])
            col_a.write(f"**{conta['nome']}** ({conta['tipo']})")
            col_b.write(f"Saldo Inicial: {formatar_moeda(conta['saldo_inicial'], simbolo)}")
            col_c.write(f"**Saldo Atual: {formatar_moeda(saldo_atual_c, simbolo)}**")

            if col_d.button("Excluir", key=f"del_conta_{conta['id']}"):
                conn = db.conectar()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM movimentacoes WHERE conta_id = ?", (int(conta["id"]),))
                cursor.execute("DELETE FROM contas WHERE id = ?", (int(conta["id"]),))
                conn.commit()
                conn.close()
                st.warning(f"Conta '{conta['nome']}' removida.")
                st.rerun()

            if total_mov_conta > 0:
                st.caption(f"   ↳ Possui {total_mov_conta} registro(s) vinculado(s).")

    st.divider()
    st.markdown("#### Adicionar Nova Conta / Banco")
    with st.form("form_nova_conta", clear_on_submit=True):
        ca, cb, cc = st.columns(3)
        nome_conta = ca.text_input("Banco (ex: Itaú PJ, Nubank PJ)")
        tipo_conta = cb.selectbox("Tipo:", ["Conta Corrente PJ", "Investimento", "Caixa / Espécie", "Conta Cartão"])
        saldo_ini = cc.number_input(f"Saldo Inicial ({simbolo}):", step=100.0, format="%.2f")

        if st.form_submit_button("Cadastrar Conta") and nome_conta:
            conn = db.conectar()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO contas (perfil_id, nome, tipo, saldo_inicial) VALUES (?, ?, ?, ?)",
                (int(perfil_id), nome_conta, tipo_conta, saldo_ini)
            )
            conn.commit()
            conn.close()
            st.success("Conta cadastrada com sucesso.")
            st.rerun()