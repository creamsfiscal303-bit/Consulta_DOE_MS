import re
import time
from datetime import date, timedelta
import pandas as pd
import requests
import streamlit as st
import socket
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Contorno de DNS: resolve www.diariooficial.ms.gov.br direto para o IP oficial (187.86.226.249)
_orig_getaddrinfo = socket.getaddrinfo
def _custom_getaddrinfo(host, port, *args, **kwargs):
    if host in ("www.diariooficial.ms.gov.br", "diariooficial.ms.gov.br"):
        return _orig_getaddrinfo("187.86.226.249", port, *args, **kwargs)
    return _orig_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = _custom_getaddrinfo

# Configuração da página
st.set_page_config(page_title="Monitoramento DOE-MS", page_icon="📰", layout="wide")

URL_BUSCA = "https://diariooficial.ms.gov.br"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Component-Type": "application/json",
    "Referer": "https://www.diariooficial.ms.gov.br/",
}

MUNICIPIOS_MS = [
    "",
    "Água Clara",
    "Alcinópolis",
    "Amambai",
    "Anastácio",
    "Anaurilândia",
    "Angélica",
    "Antônio João",
    "Aparecida do Taboado",
    "Aquidauana",
    "Aral Moreira",
    "Bandeirantes",
    "Bataguassu",
    "Batayporã",
    "Bela Vista",
    "Bodoquena",
    "Bonito",
    "Brasilândia",
    "Caarapó",
    "Camapuã",
    "Campo Grande",
    "Caracol",
    "Cassilândia",
    "Chapadão do Sul",
    "Corguinho",
    "Coronel Sapucaia",
    "Corumbá",
    "Costa Rica",
    "Coxim",
    "Deodápolis",
    "Dois Irmãos do Buriti",
    "Douradina",
    "Dourados",
    "Eldorado",
    "Fátima do Sul",
    "Figueirão",
    "Glória de Dourados",
    "Guia Lopes da Laguna",
    "Iguatemi",
    "Inocência",
    "Itaporã",
    "Itaquiraí",
    "Ivinhema",
    "Japorã",
    "Jaraguari",
    "Jardim",
    "Jateí",
    "Juti",
    "Ladário",
    "Laguna Carapã",
    "Maracaju",
    "Miranda",
    "Mundo Novo",
    "Naviraí",
    "Nioaque",
    "Nova Alvorada do Sul",
    "Nova Andradina",
    "Novo Horizonte do Sul",
    "Paraíso das Águas",
    "Paranaíba",
    "Paranhos",
    "Pedro Gomes",
    "Ponta Porã",
    "Porto Murtinho",
    "Ribas do Rio Pardo",
    "Rio Brilhante",
    "Rio Negro",
    "Rio Verde de Mato Grosso",
    "Rochedo",
    "Santa Rita do Pardo",
    "São Gabriel do Oeste",
    "Selvíria",
    "Sete Quedas",
    "Sidrolândia",
    "Sonora",
    "Tacuru",
    "Taquarussu",
    "Terenos",
    "Três Lagoas",
    "Vicentina"
]

def extrair_entidades(texto: str) -> tuple[str, str, str]:
    """Extrai CNPJs, CPFs e valores em R$ presentes no trecho."""
    cnpjs = set(re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto))
    cpfs = set(re.findall(r"\d{3}\.\d{3}\.\d{3}-\d{2}", texto))
    valores = set(re.findall(r"R\$\s?[\d\.,]+", texto))
    return (
        ", ".join(sorted(cnpjs)) if cnpjs else "-",
        ", ".join(sorted(cpfs)) if cpfs else "-",
        ", ".join(sorted(valores)) if valores else "-",
    )

@st.cache_data(ttl=600, show_spinner=False)
def consultar_api_doe(
    texto: str,
    busca_exata: bool = True,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    max_paginas: int = 10,
) -> list[dict]:
    """Consulta a API do DOE-MS com suporte a paginação e datas."""
    resultados = []
    pagina = 1
    tipo = 1 if busca_exata else 2

    while pagina <= max_paginas:
        params = {
            "tipo": tipo,
            "texto": texto,
            "pagina": pagina,
            "registrosPorPagina": 50,
        }
        if data_inicio:
            params["dataInicio"] = data_inicio.strftime("%Y-%m-%d")
        if data_fim:
            params["dataFim"] = data_fim.strftime("%Y-%m-%d")

        try:
            resp = requests.get(URL_BUSCA, params=params, headers=HEADERS, timeout=30, verify=False)
            resp.raise_for_status()
            dados = resp.json()
        except requests.exceptions.ConnectionError:
            st.error(
                "Não foi possível conectar ao servidor do Diário Oficial de MS. "
                "O portal do governo bloqueia acessos vindos de servidores fora do Brasil (como o Streamlit Cloud). "
                "Execute este painel localmente no seu computador ou em um servidor hospedado no Brasil."
            )
            return []
        except requests.exceptions.RequestException as e:
            st.error(f"Erro ao consultar a API do DOE-MS: {e}")
            return []


        itens = dados.get("paginasDiario", [])
        if not itens:
            break

        for item in itens:
            data_pub_str = item.get("dataPublicacao", "")[:10]
            # Filtro local de segurança caso a API ignore os parâmetros de data
            if data_pub_str:
                data_pub = date.fromisoformat(data_pub_str)
                if data_inicio and data_pub < data_inicio:
                    continue
                if data_fim and data_pub > data_fim:
                    continue

            trechos_brutos = item.get("hiHighlight", {}).get("texto", [])
            trecho_limpo = " | ".join(re.sub(r"</?mark>", "", t) for t in trechos_brutos)
            cnpjs, cpfs, valores = extrair_entidades(trecho_limpo)
            url_pdf = item.get("caminhoArquivo", "")
            pagina_pdf = item.get("pagina", 1)

            resultados.append({
                "Data": data_pub_str,
                "Edição": item.get("numero"),
                "Página": pagina_pdf,
                "Termo Buscado": texto,
                "CNPJs Detectados": cnpjs,
                "CPFs Detectados": cpfs,
                "Valores (R$)": valores,
                "Trecho": trecho_limpo,
                "Link PDF (Página)": f"{url_pdf}#page={pagina_pdf}" if url_pdf else "",
            })

        if pagina >= dados.get("totalDePaginas", 1):
            break

        pagina += 1
        time.sleep(0.3)

    return resultados

# --- INTERFACE DO PAINEL ---
st.title("📰 Painel de Consulta e Cruzamento — DOE/MS")
st.markdown("Pesquise publicações oficiais do Estado de Mato Grosso do Sul por empresa, documento, município ou palavra-chave.")

with st.sidebar:
    st.header("🔍 Filtros de Pesquisa")

    empresa = st.text_input("Empresa Contratada / Razão Social", placeholder="Ex: PREMACOL")
    cnpj = st.text_input("CNPJ", placeholder="Ex: 06.099.712/0001-96")
    cpf = st.text_input("CPF", placeholder="Ex: 000.000.000-00")
    municipio = st.selectbox("Município (MS)", MUNICIPIOS_MS)
    termo_livre = st.text_input("Palavra-chave / Processo / Contrato", placeholder="Ex: Dispensa de Licitação")

    st.divider()
    usar_datas = st.checkbox("Filtrar por período de publicação", value=False)
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        dt_inicio = st.date_input("Data inicial", value=date.today() - timedelta(days=30), disabled=not usar_datas)
    with col_d2:
        dt_fim = st.date_input("Data final", value=date.today(), disabled=not usar_datas)

    busca_exata = st.toggle("Busca Exata", value=True)
    max_pags = st.slider("Limite de páginas da API por termo", min_value=1, max_value=30, value=5)

    btn_buscar = st.button("Pesquisar no DOE-MS", type="primary", use_container_width=True)

# --- EXECUÇÃO DA BUSCA ---
if btn_buscar:
    termos_para_buscar = [t.strip() for t in [empresa, cnpj, cpf, termo_livre] if t.strip()]

    # Se nenhum campo textual foi preenchido, mas um município foi selecionado, busca pelo município
    if not termos_para_buscar and municipio:
        termos_para_buscar = [municipio]

    if not termos_para_buscar:
        st.warning("Preencha ao menos um campo de busca (Empresa, CNPJ, CPF, Município ou Palavra-chave).")
    else:
        todos_resultados = []
        with st.spinner("Consultando base do Diário Oficial de MS..."):
            for termo in termos_para_buscar:
                res = consultar_api_doe(
                    texto=termo,
                    busca_exata=busca_exata,
                    data_inicio=dt_inicio if usar_datas else None,
                    data_fim=dt_fim if usar_datas else None,
                    max_paginas=max_pags,
                )
                todos_resultados.extend(res)

        if not todos_resultados:
            st.info("Nenhuma publicação encontrada com os filtros informados.")
        else:
            df = pd.DataFrame(todos_resultados).drop_duplicates(subset=["Edição", "Página", "Trecho"])

            # Se houver município selecionado junto com outro termo, filtra nos trechos ou faz cruzamento
            if municipio and municipio not in termos_para_buscar:
                df_mun = df[df["Trecho"].str.contains(municipio, case=False, na=False)]
                if not df_mun.empty:
                    df = df_mun
                else:
                    st.warning(f"O município '{municipio}' não apareceu diretamente no trecho resumido; exibindo todos os resultados dos demais termos.")

            # Métricas rápidas no topo
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Ocorrências Encontradas", len(df))
            m2.metric("Edições Distintas", df["Edição"].nunique())
            m3.metric("CNPJs Citados", df[df["CNPJs Detectados"] != "-"]["CNPJs Detectados"].nunique())
            m4.metric("Período", f"{df['Data'].min()} a {df['Data'].max()}")

            # Filtro rápido local dentro dos resultados carregados
            filtro_rapido = st.text_input("🔎 Refinar nos resultados encontrados (ex: nome de órgão, secretaria, valor):", "")
            if filtro_rapido:
                df = df[df["Trecho"].str.contains(filtro_rapido, case=False, na=False)]

            # Tabela interativa com link clicável direto para a página do PDF
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Link PDF (Página)": st.column_config.LinkColumn(
                        "Abrir PDF",
                        display_text="📄 Abrir Página",
                    ),
                    "Trecho": st.column_config.TextColumn("Trecho Publicado", width="large"),
                },
            )

            # Botão de exportação CSV (compatível com Excel)
            csv_bytes = df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                label="📥 Baixar Resultados em Excel (CSV)",
                data=csv_bytes,
                file_name=f"consulta_doe_ms_{date.today()}.csv",
                mime="text/csv",
            )
