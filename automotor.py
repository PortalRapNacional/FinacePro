"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR — Cartões de Crédito & MEI               ║
║   Stack: Hugo + GitHub Pages + Gemini AI + GitHub Actions        ║
╚══════════════════════════════════════════════════════════════════╝

Fluxo:
  1. SCRAPER     → Coleta notícias de RSS financeiros
  2. DEDUP       → Filtra notícias já publicadas
  3. IA GEMINI   → Gera artigo SEO completo em Markdown
  4. HUGO        → Salva com Front Matter correto
  5. AUTO-DEPLOY → git add / commit / push
"""

import os
import re
import sys
import time
import hashlib
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
import google.generativeai as genai

# ─────────────────────────────────────────────
# CONFIGURAÇÃO DE LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTES E CONFIGURAÇÕES
# ─────────────────────────────────────────────

# Feeds RSS financeiros brasileiros
RSS_FEEDS = [
    "https://www.infomoney.com.br/feed/",
    "https://www.seucreditodigital.com.br/feed/",
    "https://valor.globo.com/rss/financas",
    "https://www.moneytimes.com.br/feed/",
    "https://www.contabeis.com.br/feed/",
]

# Palavras-chave para filtrar notícias relevantes
KEYWORDS = [
    "cartão de crédito",
    "cartao de credito",
    "mei",
    "microempreendedor",
    "empréstimo",
    "emprestimo",
    "financiamento",
    "limite de crédito",
    "fintechs",
    "conta pj",
    "crédito empresarial",
]

# Caminhos do projeto Hugo
CONTENT_DIR = Path("content/posts")
HISTORICO_FILE = Path("historico.txt")

# Número máximo de posts por execução (evita limite de API)
MAX_POSTS_POR_EXECUCAO = 3

# Delay entre chamadas à API Gemini (segundos) — respeita rate limit gratuito
API_DELAY_SECONDS = 8


# ─────────────────────────────────────────────
# MÓDULO 1 — SCRAPER DE RSS
# ─────────────────────────────────────────────

def buscar_noticias_rss(feeds: list[str], keywords: list[str]) -> list[dict]:
    """
    Percorre os feeds RSS e retorna notícias relevantes baseadas nas keywords.

    Returns:
        Lista de dicts com 'titulo', 'link' e 'fonte'.
    """
    noticias_encontradas: list[dict] = []

    for url in feeds:
        log.info(f"📡 Buscando feed: {url}")
        try:
            feed = feedparser.parse(url)

            if feed.bozo:
                log.warning(f"⚠️  Feed com problema (bozo=True): {url}")

            for entry in feed.entries:
                titulo = entry.get("title", "").strip()
                link = entry.get("link", "").strip()

                if not titulo or not link:
                    continue

                titulo_lower = titulo.lower()
                if any(kw in titulo_lower for kw in keywords):
                    noticias_encontradas.append({
                        "titulo": titulo,
                        "link": link,
                        "fonte": feed.feed.get("title", url),
                    })
                    log.info(f"   ✅ Relevante: {titulo[:70]}...")

        except Exception as e:
            log.error(f"❌ Erro ao processar feed {url}: {e}")
            continue

    log.info(f"📊 Total de notícias relevantes encontradas: {len(noticias_encontradas)}")
    return noticias_encontradas


# ─────────────────────────────────────────────
# MÓDULO 2 — DEDUPLICAÇÃO
# ─────────────────────────────────────────────

def gerar_hash_noticia(link: str) -> str:
    """Gera um hash MD5 do link para identificação única."""
    return hashlib.md5(link.encode("utf-8")).hexdigest()


def carregar_historico(arquivo: Path) -> set[str]:
    """Carrega o histórico de hashes já publicados."""
    if not arquivo.exists():
        arquivo.touch()
        log.info(f"📄 Arquivo de histórico criado: {arquivo}")
        return set()

    with open(arquivo, "r", encoding="utf-8") as f:
        hashes = {linha.strip() for linha in f if linha.strip()}

    log.info(f"📂 Histórico carregado: {len(hashes)} posts já publicados.")
    return hashes


def salvar_no_historico(arquivo: Path, hash_noticia: str) -> None:
    """Adiciona um novo hash ao histórico."""
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(hash_noticia + "\n")


def filtrar_noticias_novas(
    noticias: list[dict],
    historico: set[str],
) -> list[dict]:
    """Remove notícias que já foram publicadas."""
    novas = []
    for noticia in noticias:
        h = gerar_hash_noticia(noticia["link"])
        if h not in historico:
            noticia["hash"] = h
            novas.append(noticia)

    log.info(f"🆕 Notícias novas (após dedup): {len(novas)}")
    return novas


# ─────────────────────────────────────────────
# MÓDULO 3 — IA GEMINI (Geração de Conteúdo)
# ─────────────────────────────────────────────

def configurar_gemini() -> Optional[genai.GenerativeModel]:
    """
    Inicializa o cliente do Google Gemini com a API Key.
    A key é lida da variável de ambiente GEMINI_API_KEY.
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        log.critical(
            "🚨 GEMINI_API_KEY não encontrada! "
            "Defina a variável de ambiente antes de executar."
        )
        return None

    try:
        genai.configure(api_key=api_key)
        modelo = genai.GenerativeModel("gemini-1.5-flash")  # Modelo gratuito
        log.info("🤖 Google Gemini configurado com sucesso.")
        return modelo
    except Exception as e:
        log.error(f"❌ Falha ao configurar Gemini: {e}")
        return None


def gerar_artigo_com_ia(
    modelo: genai.GenerativeModel,
    titulo_noticia: str,
    fonte: str,
) -> Optional[str]:
    """
    Envia o prompt ao Gemini e retorna o artigo gerado em Markdown.

    Args:
        modelo: Instância do modelo Gemini.
        titulo_noticia: Título da notícia scraped.
        fonte: Nome do veículo de origem.

    Returns:
        String com o artigo em Markdown ou None em caso de erro.
    """
    prompt = f"""Aja como um especialista em finanças para MEI e pequenos empreendedores brasileiros.

Com base no título da notícia: "{titulo_noticia}" (fonte: {fonte})

Escreva um artigo de blog COMPLETO em Markdown seguindo EXATAMENTE esta estrutura:

# [Título Chamativo e Otimizado para SEO com a palavra-chave principal]

**Tempo de leitura:** X minutos

## Introdução
[2 parágrafos focados na DOR do MEI ou empreendedor. Use dados reais do mercado brasileiro. \
Crie urgência e empatia. Mencione o problema central que o leitor enfrenta hoje.]

## [Subtópico 1: Benefício ou Conceito Principal]
[2-3 parágrafos detalhados. Inclua dados, percentuais, comparações de taxas. \
Use exemplos práticos do cotidiano do MEI.]

## [Subtópico 2: Como Funciona na Prática / Passo a Passo]
[2-3 parágrafos com orientações práticas. Inclua uma lista com pelo menos 5 itens \
de dicas ou passos numerados.]

## [Subtópico 3: Cuidados, Erros Comuns e Melhores Opções]
[2-3 parágrafos sobre erros a evitar, comparativo de produtos/instituições \
e recomendações específicas para MEI.]

## Conclusão
[1 parágrafo resumindo os pontos principais e incentivando a ação.]

## FAQ — Perguntas Frequentes

**P: [Pergunta frequente 1]?**
R: [Resposta clara e direta]

**P: [Pergunta frequente 2]?**
R: [Resposta clara e direta]

**P: [Pergunta frequente 3]?**
R: [Resposta clara e direta]

---
*Artigo atualizado em {datetime.now().strftime("%d/%m/%Y")}. \
Consulte sempre um contador ou especialista financeiro.*

REGRAS OBRIGATÓRIAS:
- Escreva APENAS em português do Brasil
- Use linguagem acessível, sem jargões desnecessários
- Otimize para SEO: mencione a keyword principal 3-5x naturalmente no texto
- NÃO inclua nenhum texto fora da estrutura acima (sem introduções, sem "Claro!", etc.)
- O artigo deve ter entre 800 e 1200 palavras no total
"""

    try:
        log.info(f"🧠 Gerando artigo para: '{titulo_noticia[:60]}...'")
        resposta = modelo.generate_content(prompt)
        conteudo = resposta.text.strip()
        log.info(f"✅ Artigo gerado! ({len(conteudo)} caracteres)")
        return conteudo
    except Exception as e:
        log.error(f"❌ Erro na API do Gemini: {e}")
        return None


# ─────────────────────────────────────────────
# MÓDULO 4 — ESTRUTURADOR HUGO
# ─────────────────────────────────────────────

def extrair_titulo_do_artigo(conteudo_markdown: str) -> str:
    """
    Extrai o título H1 do Markdown gerado pela IA.
    Fallback para um título genérico se não encontrar.
    """
    for linha in conteudo_markdown.splitlines():
        if linha.startswith("# "):
            return linha[2:].strip()
    return "Artigo sobre Finanças para MEI"


def slugify(texto: str) -> str:
    """Converte um título em slug URL-friendly."""
    slug = texto.lower()
    # Remove acentos comuns do português
    substituicoes = {
        "á": "a", "à": "a", "ã": "a", "â": "a", "ä": "a",
        "é": "e", "ê": "e", "ë": "e",
        "í": "i", "î": "i", "ï": "i",
        "ó": "o", "ô": "o", "õ": "o", "ö": "o",
        "ú": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n",
    }
    for original, substituto in substituicoes.items():
        slug = slug.replace(original, substituto)

    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]  # Limite de 80 chars para URLs limpas


def detectar_categoria_e_tags(titulo: str) -> tuple[str, list[str]]:
    """Detecta categoria e tags com base no conteúdo do título."""
    titulo_lower = titulo.lower()

    tags = []
    categoria = "Finanças"

    if any(k in titulo_lower for k in ["cartão", "cartao", "crédito", "credito"]):
        categoria = "Cartão de Crédito"
        tags.extend(["cartão de crédito", "crédito", "finanças pessoais"])

    if any(k in titulo_lower for k in ["mei", "microempreendedor"]):
        categoria = "MEI"
        tags.extend(["mei", "empreendedorismo", "pequenos negócios"])

    if any(k in titulo_lower for k in ["empréstimo", "emprestimo", "financiamento"]):
        if "MEI" not in categoria:
            categoria = "Empréstimos"
        tags.extend(["empréstimo", "crédito empresarial"])

    if not tags:
        tags = ["finanças", "dinheiro", "brasil"]

    # Remove duplicatas mantendo a ordem
    tags = list(dict.fromkeys(tags))
    return categoria, tags


def gerar_front_matter(titulo: str, categoria: str, tags: list[str]) -> str:
    """Gera o bloco de Front Matter YAML para Hugo."""
    agora = datetime.now(timezone.utc)
    data_iso = agora.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    tags_yaml = "\n".join(f'  - "{tag}"' for tag in tags)

    return f"""---
title: "{titulo.replace('"', "'")}"
date: {data_iso}
draft: false
categories:
  - "{categoria}"
tags:
{tags_yaml}
description: "Artigo completo sobre {titulo[:100]}. Dicas práticas para MEI e empreendedores brasileiros."
author: "Redação Automática"
---

"""


def salvar_post_hugo(
    conteudo_markdown: str,
    pasta_posts: Path,
) -> Optional[Path]:
    """
    Salva o post com Front Matter na pasta de conteúdo do Hugo.

    Returns:
        Path do arquivo criado ou None em caso de erro.
    """
    try:
        pasta_posts.mkdir(parents=True, exist_ok=True)

        titulo = extrair_titulo_do_artigo(conteudo_markdown)
        categoria, tags = detectar_categoria_e_tags(titulo)
        front_matter = gerar_front_matter(titulo, categoria, tags)

        # Remove o H1 do corpo (já está no Front Matter como 'title')
        linhas = conteudo_markdown.splitlines()
        corpo = "\n".join(
            linha for linha in linhas
            if not linha.strip().startswith("# ")
        ).strip()

        conteudo_final = front_matter + corpo

        # Nome do arquivo baseado na data + slug
        data_str = datetime.now().strftime("%Y-%m-%d")
        slug = slugify(titulo)
        nome_arquivo = f"{data_str}-{slug}.md"
        caminho_arquivo = pasta_posts / nome_arquivo

        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            f.write(conteudo_final)

        log.info(f"💾 Post salvo: {caminho_arquivo}")
        return caminho_arquivo

    except Exception as e:
        log.error(f"❌ Erro ao salvar post: {e}")
        return None


# ─────────────────────────────────────────────
# MÓDULO 5 — AUTO-DEPLOY (Git Automation)
# ─────────────────────────────────────────────

def executar_comando_git(comando: list[str]) -> bool:
    """
    Executa um comando Git via subprocess com tratamento de erro.

    Args:
        comando: Lista com o comando e seus argumentos.

    Returns:
        True se sucesso, False caso contrário.
    """
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        if resultado.stdout:
            log.info(f"   Git: {resultado.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"❌ Erro no comando Git {' '.join(comando)}: {e.stderr.strip()}")
        return False


def fazer_deploy_git(mensagem_commit: str) -> bool:
    """
    Executa o fluxo completo de git add → commit → push.

    Returns:
        True se o push foi bem-sucedido.
    """
    log.info("🚀 Iniciando deploy automático via Git...")

    comandos = [
        (["git", "config", "user.email", "bot@blog-automator.com"], "Config email"),
        (["git", "config", "user.name", "Blog Automator Bot"], "Config nome"),
        (["git", "add", "."], "git add"),
        (["git", "commit", "-m", mensagem_commit], "git commit"),
        (["git", "push"], "git push"),
    ]

    for comando, descricao in comandos:
        log.info(f"   ▶ {descricao}: {' '.join(comando)}")
        if not executar_comando_git(comando):
            # Commit vazio não é erro crítico — pode não haver mudanças
            if "commit" in comando:
                log.warning("⚠️  Nenhuma mudança para commitar. Continuando...")
                continue
            return False

    log.info("✅ Deploy realizado com sucesso!")
    return True


# ─────────────────────────────────────────────
# ORQUESTRADOR PRINCIPAL
# ─────────────────────────────────────────────

def main() -> None:
    log.info("=" * 60)
    log.info("🏦  BLOG AUTOMATOR — Cartões de Crédito & MEI  🏦")
    log.info("=" * 60)

    # ── Etapa 1: Configurar Gemini ─────────────────────────────
    modelo = configurar_gemini()
    if modelo is None:
        log.critical("Encerrando: sem modelo de IA disponível.")
        sys.exit(1)

    # ── Etapa 2: Scraping de RSS ────────────────────────────────
    log.info("\n📡 [ETAPA 1/4] Buscando notícias nos feeds RSS...")
    todas_noticias = buscar_noticias_rss(RSS_FEEDS, KEYWORDS)

    if not todas_noticias:
        log.warning("Nenhuma notícia relevante encontrada hoje. Encerrando.")
        sys.exit(0)

    # ── Etapa 3: Deduplicação ───────────────────────────────────
    log.info("\n🔍 [ETAPA 2/4] Filtrando notícias já publicadas...")
    historico = carregar_historico(HISTORICO_FILE)
    noticias_novas = filtrar_noticias_novas(todas_noticias, historico)

    if not noticias_novas:
        log.info("🔁 Todas as notícias já foram publicadas anteriormente. Nada a fazer.")
        sys.exit(0)

    # ── Etapa 4: Geração e publicação dos posts ─────────────────
    log.info(f"\n✍️  [ETAPA 3/4] Gerando posts com IA (máx: {MAX_POSTS_POR_EXECUCAO})...")
    posts_criados = 0

    for noticia in noticias_novas[:MAX_POSTS_POR_EXECUCAO]:
        log.info(f"\n{'─' * 50}")
        log.info(f"📰 Processando: {noticia['titulo']}")

        # Gera o artigo com a IA
        artigo = gerar_artigo_com_ia(modelo, noticia["titulo"], noticia["fonte"])

        if artigo is None:
            log.warning(f"⏭️  Pulando notícia por falha na IA: {noticia['titulo'][:50]}")
            continue

        # Salva o arquivo no Hugo
        caminho = salvar_post_hugo(artigo, CONTENT_DIR)

        if caminho:
            # Registra no histórico apenas após salvar com sucesso
            salvar_no_historico(HISTORICO_FILE, noticia["hash"])
            posts_criados += 1
            log.info(f"📝 Post #{posts_criados} criado: {caminho.name}")

        # Respeita o rate limit da API gratuita
        if posts_criados < MAX_POSTS_POR_EXECUCAO:
            log.info(f"⏳ Aguardando {API_DELAY_SECONDS}s (rate limit)...")
            time.sleep(API_DELAY_SECONDS)

    # ── Etapa 5: Deploy no GitHub Pages ─────────────────────────
    log.info(f"\n🚀 [ETAPA 4/4] Publicando {posts_criados} post(s) no GitHub Pages...")

    if posts_criados == 0:
        log.warning("Nenhum post novo criado. Deploy cancelado.")
        sys.exit(0)

    data_hoje = datetime.now().strftime("%d/%m/%Y")
    mensagem = f"🤖 Auto-post: {posts_criados} novo(s) artigo(s) — {data_hoje}"

    sucesso = fazer_deploy_git(mensagem)

    log.info("\n" + "=" * 60)
    if sucesso:
        log.info(f"🎉 CONCLUÍDO! {posts_criados} post(s) publicado(s) com sucesso.")
    else:
        log.error("💥 Deploy falhou. Verifique as permissões do Git/GitHub.")
        sys.exit(1)
    log.info("=" * 60)


if __name__ == "__main__":
    main()

