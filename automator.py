"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v3 — Cartões de Crédito & MEI            ║
║   Stack: Hugo + GitHub Pages + Gemini AI + Pexels + Actions     ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import time
import hashlib
import logging
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
from google import genai

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
RSS_FEEDS = [
    "https://www.infomoney.com.br/feed/",
    "https://www.seucreditodigital.com.br/feed/",
    "https://valor.globo.com/rss/financas",
    "https://www.moneytimes.com.br/feed/",
    "https://www.contabeis.com.br/feed/",
]

KEYWORDS = [
    "cartão de crédito", "cartao de credito",
    "mei", "microempreendedor",
    "empréstimo", "emprestimo",
    "financiamento", "limite de crédito",
    "fintechs", "conta pj", "crédito empresarial",
]

CONTENT_DIR    = Path("content/posts")
HISTORICO_FILE = Path("historico.txt")
MAX_POSTS      = 3

# ── Delays e Rate Limits ──
API_DELAY      = 30   # segundos entre chamadas Gemini
PEXELS_DELAY   = 2    # segundos após busca de imagem (antes do Gemini)

# ── Modelos ──
GEMINI_MODEL          = "gemini-1.5-flash"
GEMINI_MAX_TENTATIVAS = 3

# ── Mapeamento de categorias → termos de busca em inglês (Pexels) ──
PEXELS_QUERY_MAP = {
    "Cartão de Crédito": "credit card finance business",
    "MEI":               "small business entrepreneur brazil",
    "Empréstimos":       "bank loan money business",
    "Finanças":          "personal finance money investment",
}

# ── Imagem de fallback (usada se Pexels falhar ou key ausente) ──
PEXELS_FALLBACK_IMAGE = "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg"
PEXELS_FALLBACK_ALT   = "Finanças e crédito para empreendedores"


# ═══════════════════════════════════════════════════════════════
# MÓDULO 1 — SCRAPER RSS
# ═══════════════════════════════════════════════════════════════

def buscar_noticias(feeds: list, keywords: list) -> list:
    encontradas = []
    for url in feeds:
        log.info(f"📡 Feed: {url}")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                titulo = entry.get("title", "").strip()
                link   = entry.get("link",  "").strip()
                if not titulo or not link:
                    continue
                if any(kw in titulo.lower() for kw in keywords):
                    encontradas.append({
                        "titulo": titulo,
                        "link":   link,
                        "fonte":  feed.feed.get("title", url),
                    })
                    log.info(f"   ✅ {titulo[:70]}")
        except Exception as e:
            log.error(f"❌ Erro no feed {url}: {e}")
    log.info(f"📊 Total relevante: {len(encontradas)}")
    return encontradas


# ═══════════════════════════════════════════════════════════════
# MÓDULO 2 — DEDUPLICAÇÃO
# ═══════════════════════════════════════════════════════════════

def _hash(link: str) -> str:
    return hashlib.md5(link.encode()).hexdigest()

def carregar_historico(arq: Path) -> set:
    if not arq.exists():
        arq.touch()
        return set()
    with open(arq, "r", encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}

def salvar_historico(arq: Path, h: str) -> None:
    with open(arq, "a", encoding="utf-8") as f:
        f.write(h + "\n")

def filtrar_novas(noticias: list, historico: set) -> list:
    novas = []
    for n in noticias:
        h = _hash(n["link"])
        if h not in historico:
            n["hash"] = h
            novas.append(n)
    log.info(f"🆕 Novas após dedup: {len(novas)}")
    return novas


# ═══════════════════════════════════════════════════════════════
# MÓDULO 3 — IMAGENS (PEXELS API)
# ═══════════════════════════════════════════════════════════════

def buscar_imagem_pexels(categoria: str) -> tuple[str, str]:
    """
    Busca uma imagem no Pexels baseada na categoria do artigo.
    Retorna (url_imagem, alt_text).

    - Usa termos em inglês para melhores resultados no Pexels.
    - Seleciona a foto de maior resolução (landscape) da primeira página.
    - Em caso de falha (sem API key, erro de rede, 0 resultados),
      retorna a imagem de fallback sem lançar exceção.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        log.warning("⚠️  PEXELS_API_KEY não encontrada. Usando imagem fallback.")
        return PEXELS_FALLBACK_IMAGE, PEXELS_FALLBACK_ALT

    query = PEXELS_QUERY_MAP.get(categoria, PEXELS_QUERY_MAP["Finanças"])
    query_encoded = urllib.parse.quote(query)
    url = f"https://api.pexels.com/v1/search?query={query_encoded}&per_page=5&orientation=landscape"

    try:
        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        fotos = data.get("photos", [])
        if not fotos:
            log.warning(f"⚠️  Nenhuma foto encontrada para '{query}'. Usando fallback.")
            return PEXELS_FALLBACK_IMAGE, PEXELS_FALLBACK_ALT

        foto  = fotos[0]
        img_url = foto["src"].get("large2x") or foto["src"]["original"]
        alt_text = foto.get("alt") or f"{categoria} - FinacePro"

        log.info(f"🖼️  Imagem encontrada: {img_url[:60]}...")
        return img_url, alt_text

    except Exception as e:
        log.warning(f"⚠️  Erro ao buscar imagem no Pexels: {e}. Usando fallback.")
        return PEXELS_FALLBACK_IMAGE, PEXELS_FALLBACK_ALT


# ═══════════════════════════════════════════════════════════════
# MÓDULO 4 — IA GEMINI
# ═══════════════════════════════════════════════════════════════

def configurar_gemini():
    """Inicializa e retorna o client do Gemini."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.critical("❌ ERRO: GEMINI_API_KEY não encontrada!")
        sys.exit(1)
    client = genai.Client(api_key=api_key)
    log.info(f"🤖 Gemini configurado. Modelo: {GEMINI_MODEL}")
    return client


def gerar_artigo(client, titulo: str, fonte: str) -> Optional[str]:
    """
    Gera artigo via Gemini com retry automático em caso de erro 429.
    - Troca para gemini-1.5-flash (cota separada do 2.0-flash)
    - Retry com backoff exponencial (RESOURCE_EXHAUSTED / 429)
    - Extrai o tempo de espera sugerido pela própria API quando disponível
    - Distingue erros de cota (retriáveis) de erros fatais (não retriáveis)
    """
    data_hoje = datetime.now().strftime("%d/%m/%Y")

    prompt = (
        "Aja como especialista em finanças para MEI e empreendedores brasileiros.\n\n"
        f"Com base na notícia: '{titulo}' (fonte: {fonte})\n\n"
        "Escreva um artigo de blog COMPLETO em Markdown com esta estrutura EXATA:\n\n"
        "# [Título chamativo e otimizado para SEO]\n\n"
        "**Tempo de leitura:** X minutos\n\n"
        "## Introdução\n"
        "[2 parágrafos focados na DOR do MEI. Use dados reais do mercado brasileiro. "
        "Crie urgência e empatia.]\n\n"
        "## [Subtópico 1 — Benefício ou conceito principal]\n"
        "[2-3 parágrafos. Inclua dados, percentuais, comparações de taxas.]\n\n"
        "## [Subtópico 2 — Como funciona na prática]\n"
        "[Lista numerada com pelo menos 5 passos práticos + 1-2 parágrafos explicativos.]\n\n"
        "## [Subtópico 3 — Erros comuns e melhores opções]\n"
        "[2-3 parágrafos com cuidados, comparativo de instituições e recomendações para MEI.]\n\n"
        "## Conclusão\n"
        "[1 parágrafo resumindo e incentivando a ação.]\n\n"
        "## FAQ — Perguntas Frequentes\n\n"
        "**P: [Pergunta 1]?**\n"
        "R: [Resposta objetiva]\n\n"
        "**P: [Pergunta 2]?**\n"
        "R: [Resposta objetiva]\n\n"
        "**P: [Pergunta 3]?**\n"
        "R: [Resposta objetiva]\n\n"
        "---\n"
        f"*Atualizado em {data_hoje}. Consulte sempre um especialista financeiro.*\n\n"
        "REGRAS:\n"
        "- Português do Brasil apenas\n"
        "- Linguagem acessível, sem jargões\n"
        "- Mencione a keyword principal 3-5x naturalmente\n"
        "- NÃO inclua texto fora da estrutura (sem 'Claro!', sem introduções)\n"
        "- Entre 800 e 1200 palavras"
    )

    for tentativa in range(1, GEMINI_MAX_TENTATIVAS + 1):
        try:
            log.info(f"🧠 Tentativa {tentativa}/{GEMINI_MAX_TENTATIVAS}: '{titulo[:60]}...'")
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            conteudo = response.text.strip()
            log.info(f"✅ Artigo gerado ({len(conteudo)} chars)")
            return conteudo

        except Exception as e:
            erro_str = str(e)

            if "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str:
                match = re.search(r"retry in (\d+)", erro_str, re.IGNORECASE)
                espera_api    = int(match.group(1)) + 5 if match else None
                espera_backoff = 60 * (2 ** (tentativa - 1))
                espera = espera_api if espera_api else espera_backoff

                if tentativa < GEMINI_MAX_TENTATIVAS:
                    log.warning(
                        f"⏳ Cota atingida (429). Aguardando {espera}s antes "
                        f"da tentativa {tentativa + 1}/{GEMINI_MAX_TENTATIVAS}..."
                    )
                    time.sleep(espera)
                else:
                    log.error(
                        f"❌ Cota esgotada após {GEMINI_MAX_TENTATIVAS} tentativas. "
                        "Verifique seu plano em: https://ai.dev/rate-limit"
                    )
            else:
                log.error(f"❌ Erro inesperado na API Gemini: {e}")
                return None

    log.error(f"❌ Todas as {GEMINI_MAX_TENTATIVAS} tentativas falharam. Pulando artigo.")
    return None


# ═══════════════════════════════════════════════════════════════
# MÓDULO 5 — ESTRUTURADOR HUGO
# ═══════════════════════════════════════════════════════════════

def extrair_h1(md: str) -> str:
    for linha in md.splitlines():
        if linha.startswith("# "):
            return linha[2:].strip()
    return "Artigo sobre Finanças para MEI"


def slugify(texto: str) -> str:
    slug = texto.lower()
    trocas = {
        "á":"a","à":"a","ã":"a","â":"a","ä":"a",
        "é":"e","ê":"e","ë":"e","í":"i","î":"i",
        "ó":"o","ô":"o","õ":"o","ö":"o","ú":"u",
        "û":"u","ü":"u","ç":"c","ñ":"n",
    }
    for orig, sub in trocas.items():
        slug = slug.replace(orig, sub)
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80]


def detectar_meta(titulo: str) -> tuple:
    tl = titulo.lower()
    categoria, tags = "Finanças", []
    if any(k in tl for k in ["cartão","cartao","crédito","credito"]):
        categoria = "Cartão de Crédito"
        tags += ["cartão de crédito","crédito","finanças pessoais"]
    if any(k in tl for k in ["mei","microempreendedor"]):
        categoria = "MEI"
        tags += ["mei","empreendedorismo","pequenos negócios"]
    if any(k in tl for k in ["empréstimo","emprestimo","financiamento"]):
        if categoria == "Finanças":
            categoria = "Empréstimos"
        tags += ["empréstimo","crédito empresarial"]
    if not tags:
        tags = ["finanças","dinheiro","brasil"]
    return categoria, list(dict.fromkeys(tags))


def front_matter(titulo: str, categoria: str, tags: list,
                 img_url: str, img_alt: str) -> str:
    """
    Gera o front matter YAML com bloco `cover` para o tema PaperMod.
    O campo `author` usa 'Conselho Editorial FinacePro' para E-E-A-T.
    """
    data        = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    tags_yaml   = "\n".join(f'  - "{t}"' for t in tags)
    titulo_safe = titulo.replace('"', "'")
    img_alt_safe = img_alt.replace('"', "'")

    return (
        f'---\n'
        f'title: "{titulo_safe}"\n'
        f'date: {data}\n'
        f'draft: false\n'
        f'author: "Conselho Editorial FinacePro"\n'
        f'categories:\n'
        f'  - "{categoria}"\n'
        f'tags:\n'
        f'{tags_yaml}\n'
        f'description: "Artigo sobre {titulo_safe[:80]}. Dicas para MEI brasileiros."\n'
        f'cover:\n'
        f'  image: "{img_url}"\n'
        f'  alt: "{img_alt_safe}"\n'
        f'  caption: "Fonte: Pexels"\n'
        f'  relative: false\n'
        f'  hidden: false\n'
        f'---\n\n'
    )


def salvar_post(conteudo_md: str, pasta: Path,
                img_url: str, img_alt: str) -> Optional[Path]:
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        titulo    = extrair_h1(conteudo_md)
        cat, tags = detectar_meta(titulo)
        fm        = front_matter(titulo, cat, tags, img_url, img_alt)

        corpo = "\n".join(
            l for l in conteudo_md.splitlines()
            if not l.strip().startswith("# ")
        ).strip()

        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo)}.md"
        path = pasta / nome
        path.write_text(fm + corpo, encoding="utf-8")
        log.info(f"💾 Post salvo: {path}")
        return path
    except Exception as e:
        log.error(f"❌ Erro ao salvar post: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# ORQUESTRADOR
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    log.info("=" * 60)
    log.info("🏦  BLOG AUTOMATOR v3 — Cartões de Crédito & MEI")
    log.info("=" * 60)

    client = configurar_gemini()

    log.info("\n📡 [1/4] Buscando notícias RSS...")
    noticias = buscar_noticias(RSS_FEEDS, KEYWORDS)
    if not noticias:
        log.warning("Nenhuma notícia encontrada. Encerrando.")
        sys.exit(0)

    log.info("\n🔍 [2/4] Filtrando duplicatas...")
    historico = carregar_historico(HISTORICO_FILE)
    novas     = filtrar_novas(noticias, historico)
    if not novas:
        log.info("Todas as notícias já foram publicadas. Nada a fazer.")
        sys.exit(0)

    log.info(f"\n✍️  [3/4] Gerando posts (máx: {MAX_POSTS})...")
    criados = 0
    for noticia in novas[:MAX_POSTS]:
        log.info(f"\n{'─'*50}")

        # ── Passo 1: detectar categoria para guiar a busca de imagem ──
        _, tags_temp = detectar_meta(noticia["titulo"])
        cat_temp, _  = detectar_meta(noticia["titulo"])

        # ── Passo 2: buscar imagem no Pexels ──
        log.info("🖼️  Buscando imagem no Pexels...")
        img_url, img_alt = buscar_imagem_pexels(cat_temp)

        # ── Passo 3: pequena pausa antes de chamar o Gemini ──
        log.info(f"⏳ Aguardando {PEXELS_DELAY}s (sincronização Pexels → Gemini)...")
        time.sleep(PEXELS_DELAY)

        # ── Passo 4: gerar artigo com o Gemini ──
        artigo = gerar_artigo(client, noticia["titulo"], noticia["fonte"])
        if artigo is None:
            continue

        # ── Passo 5: salvar post com imagem no front matter ──
        path = salvar_post(artigo, CONTENT_DIR, img_url, img_alt)
        if path:
            salvar_historico(HISTORICO_FILE, noticia["hash"])
            criados += 1

        if criados < MAX_POSTS:
            log.info(f"⏳ Aguardando {API_DELAY}s entre posts (rate limit Gemini)...")
            time.sleep(API_DELAY)

    log.info(f"\n🚀 [4/4] Publicando {criados} post(s)...")
    if criados == 0:
        log.warning("Nenhum post criado. Deploy cancelado.")
        sys.exit(0)

    log.info("\n" + "=" * 60)
    log.info(f"🎉 CONCLUÍDO! {criados} post(s) gerado(s) e salvo(s).")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
