"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v4.3 — Cartões de Crédito & MEI          ║
║   Stack: Hugo + GitHub Pages + Gemini AI + Pexels + Actions     ║
║   [FIX v4.3] Keywords sem espaço + Mais captura de notícias     ║
╚══════════════════════════════════════════════════════════════════╝
"""
import os
import re
import sys
import time
import hashlib
import json
import random
import logging
import urllib.request
import urllib.parse
import urllib.error
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
    # [NEW] Fallback adicional para aumentar captura
    "https://economia.uol.com.br/rss/ultimas-noticias.xml",
]

# ✅ CORREÇÃO CRÍTICA: Keywords SEM espaço no final + mais termos de cauda longa
KEYWORDS = [
    "cartão de crédito", "cartao de credito",    "mei", "microempreendedor",
    "empréstimo", "emprestimo",
    "financiamento", "limite de crédito", "limite de credito",
    "fintechs", "conta pj", "crédito empresarial", "credito empresarial",
    # [NEW] Keywords extras para ampliar captura (sem espaço!)
    "cartão mei", "crédito pj", "taxa de juros",
    "score serasa", "antecipação recebíveis", "liberação crédito",
    "aprovação cartão", "negociação dívida", "serasa limpa nome",
    "conta digital pj", "saque aniversário", "juros rotativo",
]

CONTENT_DIR    = Path("content/posts")
HISTORICO_FILE = Path("historico.txt")
CACHE_DIR      = Path(".gemini_cache")

# Detecta tier para limitar posts no free
IS_FREE_TIER = os.environ.get("GEMINI_TIER", "free").lower() == "free"
MAX_POSTS    = 1 if IS_FREE_TIER else 3

# ── Delays ──
API_DELAY    = 30 if IS_FREE_TIER else 15
PEXELS_DELAY = 2

GEMINI_MODEL          = "gemini-2.0-flash"
GEMINI_MAX_TENTATIVAS = 3

# ✅ CORREÇÃO: Queries Pexels SEM espaço no final
PEXELS_QUERY_MAP = {
    "Cartão de Crédito": "credit card business finance",
    "MEI":                "small business entrepreneur",
    "Empréstimos":        "bank loan money finance",
    "Finanças":           "personal finance investment money",
}

PEXELS_FALLBACK = {
    "url": "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg",
    "alt": "Finanças e crédito para empreendedores brasileiros",
}

PEXELS_USER_AGENT = (
    "Mozilla/5.0 (compatible; FinaceProBot/4.3; "
    "+https://portalrapnacional.github.io/FinacePro/)"
)

# ✅ CORREÇÃO: Keywords primárias SEM espaço no final
KEYWORD_PRIMARIA = {
    "Cartão de Crédito": "cartão de crédito para MEI",
    "MEI":                "MEI microempreendedor individual",
    "Empréstimos":        "empréstimo para MEI",
    "Finanças":           "educação financeira para empreendedores",}

# ─────────────────────────────────────────────
# FUNÇÕES DE CACHE EM DISCO
# ─────────────────────────────────────────────
def _cache_key(prompt: str) -> str:
    return hashlib.md5(prompt.encode("utf-8")).hexdigest()

def _load_from_cache(prompt: str) -> Optional[str]:
    cache_file = CACHE_DIR / f"{_cache_key(prompt)}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) < 7 * 24 * 3600:
            log.info(f"♻️ Cache HIT: {data.get('titulo', 'artigo')[:50]}...")
            return data["content"]
        else:
            cache_file.unlink()
            return None
    except Exception as e:
        log.warning(f"⚠️ Erro ao ler cache: {e}")
        return None

def _save_to_cache(prompt: str, content: str, titulo: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{_cache_key(prompt)}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "content": content,
                "titulo": titulo,
                "timestamp": time.time()
            }, f, ensure_ascii=False, indent=2)
        log.info(f"💾 Cache SAVE: {titulo[:50]}...")
    except Exception as e:
        log.warning(f"⚠️ Erro ao salvar cache: {e}")

# ─────────────────────────────────────────────
# MÓDULO 1 — SCRAPER RSS
# ─────────────────────────────────────────────
def buscar_noticias(feeds: list, keywords: list) -> list:
    encontradas = []
    for url in feeds:
        log.info(f"📡 Feed: {url}")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                titulo = entry.get("title", "").strip()                link   = entry.get("link", "").strip()
                if not titulo or not link:
                    continue
                # ✅ CORREÇÃO: keywords sem espaço = match correto
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

# ─────────────────────────────────────────────
# MÓDULO 2 — DEDUPLICAÇÃO
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# MÓDULO 3 — IMAGENS (PEXELS API)
# ─────────────────────────────────────────────
def buscar_imagem_pexels(categoria: str) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        log.warning("⚠️ PEXELS_API_KEY ausente. Usando imagem fallback.")        return PEXELS_FALLBACK

    query = PEXELS_QUERY_MAP.get(categoria, PEXELS_QUERY_MAP["Finanças"])
    query_encoded = urllib.parse.quote(query)
    endpoint = (
        f"https://api.pexels.com/v1/search?query={query_encoded}&per_page=5&orientation=landscape"
    )

    try:
        req = urllib.request.Request(
            endpoint,
            headers={
                "Authorization": api_key,
                "User-Agent": PEXELS_USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        fotos = data.get("photos", [])
        if not fotos:
            log.warning(f"⚠️ Sem fotos Pexels para '{query}'. Fallback ativo.")
            return PEXELS_FALLBACK

        foto = fotos[0]
        img_url = foto["src"].get("large2x") or foto["src"]["original"]
        alt_txt = (foto.get("alt") or f"{categoria} — FinacePro").strip()

        log.info(f"🖼️ Pexels OK: {img_url[:70]}...")
        return {"url": img_url, "alt": alt_txt}

    except urllib.error.HTTPError as e:
        log.warning(f"⚠️ Pexels HTTP {e.code} {e.reason}. Fallback ativo.")
        return PEXELS_FALLBACK
    except Exception as e:
        log.warning(f"⚠️ Pexels erro: {e}. Fallback ativo.")
        return PEXELS_FALLBACK

# ─────────────────────────────────────────────
# MÓDULO 4 — IA GEMINI
# ─────────────────────────────────────────────
def configurar_gemini():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        log.critical("❌ GEMINI_API_KEY não encontrada!")
        sys.exit(1)
    client = genai.Client(api_key=api_key)
    tier = "PAGO" if not IS_FREE_TIER else "FREE"
    log.info(f"🤖 Gemini OK. Modelo: {GEMINI_MODEL} | Tier: {tier} | Max posts: {MAX_POSTS}")
    return client
def gerar_artigo(client, titulo: str, fonte: str, categoria: str) -> Optional[str]:
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    ano_atual = datetime.now().year
    kw_primaria = KEYWORD_PRIMARIA.get(categoria, "finanças para MEI")

    prompt = f"""Você é jornalista financeiro sênior especializado em MEI e crédito empresarial no Brasil, com 15 anos de experiência. Escreva para o FinacePro, portal de referência em finanças para microempreendedores.
NOTÍCIA BASE: "{titulo}" (fonte: {fonte})
KEYWORD PRIMÁRIA: "{kw_primaria}"
DATA: {data_hoje}
═══ ESTRUTURA OBRIGATÓRIA (Markdown) ═══
[Título com número + benefício + keyword | ex: "7 Melhores Cartões de Crédito para MEI com Limite Alto em {ano_atual}"]
Meta description: [Exatamente 150-160 caracteres: keyword + benefício principal + CTA implícito. Ex: "Descubra os melhores cartões de crédito para MEI em {ano_atual}: compare taxas, limites e cashback. Guia completo para microempreendedores."]
Tempo de leitura: X minutos | Atualizado em: {data_hoje}
Por Que Todo MEI Precisa Saber Disso Agora
[2 parágrafos FORTES. Abra com dado real do Banco Central, IBGE ou Sebrae. Crie urgência: o que o MEI perde sem essa informação. Use "{kw_primaria}" na primeira frase do primeiro parágrafo.]
[Subtítulo 1 — Benefício concreto em números]
[3 parágrafos. Inclua: (1) comparativo de taxas entre 3 instituições reais, (2) percentual de economia ou ganho para o MEI, (3) critérios de aprovação. Cite dados do Banco Central ou Serasa Experian.]
[Subtítulo 2 — Como o MEI conquista isso na prática]
Siga estes passos:
[Ação 1]: [explicação direta]
[Ação 2]: [explicação direta]
[Ação 3]: [explicação direta]
[Ação 4]: [explicação direta]
[Ação 5]: [explicação direta]
[1 parágrafo de contexto com dica prática que poucos conhecem.]
[Subtítulo 3 — Os 3 erros que custam dinheiro ao MEI]
[3 parágrafos. Cada um: erro comum + como evitar + produto/instituição que resolve. Mencione fintechs reais: Nubank PJ, Inter PJ, C6 Bank, Mercado Pago, Itaú Empresas, Bradesco MEI, Sicoob.]
Comparativo: Melhores Opções para MEI em {ano_atual}
| Instituição | Anuidade | Limite Inicial | Cashback | Melhor Para |
| --- | --- | --- | --- | --- |
| [Opção 1] | [valor] | [valor] | [%] | [perfil MEI] |
| [Opção 2] | [valor] | [valor] | [%] | [perfil MEI] |
| [Opção 3] | [valor] | [valor] | [%] | [perfil MEI] |
| [Opção 4] | [valor] | [valor] | [%] | [perfil MEI] |
Conclusão: Vale a Pena para o Seu Negócio?
[1 parágrafo direto. 2 frases sobre quem deve agir agora. Finalize com: "Veja também nossos guias sobre [tópico relacionado] e [outro tópico] para otimizar ainda mais as finanças do seu MEI."]
FAQ — Perguntas Frequentes
P: Qual o melhor {kw_primaria} em {ano_atual}?
R: [2-3 frases com dado concreto e recomendação objetiva]
P: MEI negativado pode conseguir cartão de crédito ou empréstimo?
R: [2-3 frases com opções reais para negativados]
P: Como aumentar o limite de crédito sendo MEI?
R: [2-3 frases com passos práticos verificáveis]
P: Conta PJ ou conta MEI: qual é melhor para conseguir crédito?
R: [2-3 frases com comparação direta]
Conteúdo produzido pelo Conselho Editorial FinacePro em {data_hoje}. As informações têm caráter educativo. Consulte um especialista financeiro antes de contratar qualquer produto de crédito.
═══ REGRAS ABSOLUTAS ═══
Português do Brasil, linguagem acessível (nível ensino médio)
"{kw_primaria}" aparece 4 a 6 vezes de forma natural no textoAPENAS dados verificáveis: use "conforme Banco Central", "segundo Sebrae" etc.
NÃO escreva nada antes do # do título (sem "Claro!", "Aqui está:", etc.)
Entre 950 e 1.300 palavras no total
A tabela comparativa é OBRIGATÓRIA e deve ter 4 linhas"""

    # Verifica cache antes de chamar API
    cached = _load_from_cache(prompt)
    if cached:
        return cached

    for tentativa in range(1, GEMINI_MAX_TENTATIVAS + 1):
        try:
            log.info(f"🧠 Tentativa {tentativa}/{GEMINI_MAX_TENTATIVAS}: '{titulo[:55]}...'")
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            conteudo = response.text.strip()
            log.info(f"✅ Artigo gerado ({len(conteudo)} chars)")
            
            # Salva no cache após sucesso
            _save_to_cache(prompt, conteudo, titulo)
            return conteudo

        except Exception as e:
            erro_str = str(e)
            if "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str:
                base_delay = 30 * (2 ** (tentativa - 1))
                jitter = random.uniform(0, 15)
                espera = int(base_delay + jitter)
                
                if tentativa < GEMINI_MAX_TENTATIVAS:
                    log.warning(f"⏳ Rate limit Gemini. Aguardando {espera}s (tentativa {tentativa+1}/3)...")
                    time.sleep(espera)
                else:
                    log.warning(f"⚠️ Cota Gemini esgotada para '{titulo[:50]}'. Post adiado.")
                    return None
            else:
                log.error(f"❌ Erro Gemini não-retry: {e}")
                return None
    
    log.error(f"❌ Falhou após {GEMINI_MAX_TENTATIVAS} tentativas.")
    return None

# ─────────────────────────────────────────────
# MÓDULO 5 — ESTRUTURADOR HUGO
# ─────────────────────────────────────────────
def extrair_h1(md: str) -> str:
    for linha in md.splitlines():
        if linha.startswith("# "):            return linha[2:].strip()
    return "Artigo sobre Finanças para MEI"

def extrair_meta_description(md: str, titulo_safe: str) -> str:
    for linha in md.splitlines():
        if linha.strip().startswith("Meta description:"):
            desc = linha.replace("Meta description:", "").strip()
            if len(desc) > 50:
                return desc[:160]
    return f"Guia completo: {titulo_safe[:70]}. Dicas práticas para MEI sobre crédito, cartões e finanças empresariais no Brasil."[:160]

def slugify(texto: str) -> str:
    slug = texto.lower()
    trocas = {"á":"a","à":"a","ã":"a","â":"a","ä":"a","é":"e","ê":"e","ë":"e","í":"i","î":"i","ó":"o","ô":"o","õ":"o","ö":"o","ú":"u","û":"u","ü":"u","ç":"c","ñ":"n"}
    for orig, sub in trocas.items():
        slug = slug.replace(orig, sub)
    slug = re.sub(r"[^a-z0-9\s-]", " ", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80]

def detectar_meta(titulo: str) -> tuple:
    tl = titulo.lower()
    categoria, tags = "Finanças", []
    if any(k in tl for k in ["cartão", "cartao", "crédito", "credito"]):
        categoria = "Cartão de Crédito"
        tags += ["cartão de crédito", "crédito", "finanças pessoais"]
    if any(k in tl for k in ["mei", "microempreendedor"]):
        if categoria == "Finanças":
            categoria = "MEI"
        tags += ["mei", "empreendedorismo", "pequenos negócios"]
    if any(k in tl for k in ["empréstimo", "emprestimo", "financiamento"]):
        if categoria == "Finanças":
            categoria = "Empréstimos"
        tags += ["empréstimo", "crédito empresarial"]
    if not tags:
        tags = ["finanças", "dinheiro", "brasil"]
    return categoria, list(dict.fromkeys(tags))

def front_matter(titulo: str, categoria: str, tags: list, img: dict, meta_desc: str) -> str:
    data = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    tags_yaml = "\n ".join(f'  - "{t}"' for t in tags)
    titulo_safe = titulo.replace('"', "'")
    alt_safe = img["alt"].replace('"', "'")
    desc_safe = meta_desc.replace('"', "'")
    kw_inline = ", ".join(tags[:5])
    return (
        f'---\n'
        f'title: "{titulo_safe}"\n'
        f'date: {data}\n'
        f'draft: false\n'        f'author: "Conselho Editorial FinacePro"\n'
        f'categories:\n'
        f'  - "{categoria}"\n'
        f'tags:\n'
        f'{tags_yaml}\n'
        f'keywords: "{kw_inline}"\n'
        f'description: "{desc_safe}"\n'
        f'cover:\n'
        f'  image: "{img["url"]}"\n'
        f'  alt: "{alt_safe}"\n'
        f'  caption: "Crédito: Pexels"\n'
        f'  relative: false\n'
        f'  hidden: false\n'
        f'ShowToc: true\n'
        f'TocOpen: false\n'
        f'---\n\n'
    )

def limpar_corpo(md: str) -> str:
    linhas = []
    for linha in md.splitlines():
        if linha.strip().startswith("# "):
            continue
        if linha.strip().startswith("Meta description:"):
            continue
        linhas.append(linha)
    return "\n".join(linhas).strip()

def salvar_post(conteudo_md: str, pasta: Path, img: dict) -> Optional[Path]:
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        titulo = extrair_h1(conteudo_md)
        cat, tags = detectar_meta(titulo)
        titulo_safe = titulo.replace('"', "'")
        meta_desc = extrair_meta_description(conteudo_md, titulo_safe)
        fm = front_matter(titulo, cat, tags, img, meta_desc)
        corpo = limpar_corpo(conteudo_md)
        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo)}.md"
        path = pasta / nome
        path.write_text(fm + corpo, encoding="utf-8")
        log.info(f"💾 Post salvo: {path}")
        return path
    except Exception as e:
        log.error(f"❌ Erro ao salvar post: {e}")
        return None

# ─────────────────────────────────────────────
# ORQUESTRADOR PRINCIPAL
# ─────────────────────────────────────────────
def main() -> None:    log.info("=" * 60)
    log.info("🏦 BLOG AUTOMATOR v4.3 — Cartões de Crédito & MEI")
    log.info(f"📊 Tier: {'PAGO (3 posts)' if not IS_FREE_TIER else 'FREE (1 post)'}")
    log.info("=" * 60)
    
    client = configurar_gemini()

    log.info("\n📡 [1/4] Buscando notícias RSS...")
    noticias = buscar_noticias(RSS_FEEDS, KEYWORDS)
    if not noticias:
        log.warning("⚠️ Nenhuma notícia encontrada. Encerrando graceful.")
        sys.exit(0)

    log.info("\n🔍 [2/4] Filtrando duplicatas...")
    historico = carregar_historico(HISTORICO_FILE)
    novas = filtrar_novas(noticias, historico)
    if not novas:
        log.info("✅ Todas as notícias já foram publicadas. Nada a fazer.")
        sys.exit(0)

    log.info(f"\n✍️ [3/4] Gerando posts (máx: {MAX_POSTS})...")
    criados = 0
    for noticia in novas[:MAX_POSTS]:
        log.info(f"\n{'─' * 55}")
        categoria, _ = detectar_meta(noticia["titulo"])
        
        log.info("🖼️ Buscando imagem no Pexels...")
        img = buscar_imagem_pexels(categoria)
        
        log.info(f"⏳ Pausa {PEXELS_DELAY}s (sincronização Pexels → Gemini)...")
        time.sleep(PEXELS_DELAY)
        
        log.info("🧠 Gerando artigo com Gemini...")
        artigo = gerar_artigo(client, noticia["titulo"], noticia["fonte"], categoria)
        
        if artigo is None:
            log.warning(f"⚠️ Pulando post: '{noticia['titulo'][:50]}...'")
            continue
        
        path = salvar_post(artigo, CONTENT_DIR, img)
        if path:
            salvar_historico(HISTORICO_FILE, noticia["hash"])
            criados += 1
            log.info(f"✅ Post #{criados} criado com sucesso!")
        
        if criados < MAX_POSTS and criados > 0:
            log.info(f"⏳ Pausa {API_DELAY}s entre posts (rate limit Gemini)...")
            time.sleep(API_DELAY)

    log.info(f"\n🚀 [4/4] Finalizando ({criados} post(s) criado(s))...")    
    if criados == 0:
        log.warning("⚠️ Nenhum post criado hoje. Workflow concluído sem erros.")
        sys.exit(0)
    
    log.info("\n" + "=" * 60)
    log.info(f"🎉 CONCLUÍDO! {criados} post(s) gerado(s) e salvo(s).")
    log.info("💡 Dica: Monitore seu uso em https://aistudio.google.com/app/quota")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
