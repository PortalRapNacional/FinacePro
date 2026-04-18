"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v4.5 — Cartões de Crédito & MEI          ║
║   [FIX v4.5] Anti-429: 1 post/dia free + cache + detecção quota ║
╚══════════════════════════════════════════════════════════════════╝
"""
import os, re, sys, time, hashlib, logging, json, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import feedparser
from google import genai

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
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
    "https://economia.uol.com.br/rss/ultimas-noticias.xml",
]

# ✅ CORREÇÃO: Keywords SEM espaço no final
KEYWORDS = [
    "cartão de crédito", "cartao de credito", "mei", "microempreendedor",
    "empréstimo", "emprestimo", "financiamento", "limite de crédito", "limite de credito",
    "fintechs", "conta pj", "crédito empresarial", "credito empresarial",
    "cartão mei", "crédito pj", "taxa de juros", "score serasa",
    "antecipação recebíveis", "liberação crédito", "aprovação cartão",
]

CONTENT_DIR = Path("content/posts")
HISTORICO_FILE = Path("historico.txt")
CACHE_DIR = Path(".gemini_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ✅ DETECTA FREE TIER E LIMITA PARA 1 POST/DIA
IS_FREE_TIER = os.environ.get("GEMINI_TIER", "free").lower() == "free"
MAX_POSTS = 1 if IS_FREE_TIER else 3

API_DELAY = 45 if IS_FREE_TIER else 20  # Mais conservador no free tier
PEXELS_DELAY = 2
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_MAX_TENTATIVAS = 2 if IS_FREE_TIER else 3  # Menos tentativas no free para não gastar quota

# ✅ CORREÇÃO: Queries Pexels SEM espaço
PEXELS_QUERY_MAP = {
    "Cartão de Crédito": "credit card business finance",
    "MEI": "small business entrepreneur",
    "Empréstimos": "bank loan money finance",
    "Finanças": "personal finance investment money",
}
PEXELS_FALLBACK = {"url": "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg", "alt": "Finanças e crédito para empreendedores brasileiros"}
PEXELS_USER_AGENT = "Mozilla/5.0 (compatible; FinaceProBot/4.5; +https://portalrapnacional.github.io/FinacePro/)"
KEYWORD_PRIMARIA = {
    "Cartão de Crédito": "cartão de crédito para MEI",
    "MEI": "MEI microempreendedor individual",
    "Empréstimos": "empréstimo para MEI",
    "Finanças": "educação financeira para empreendedores",
}

# ─────────────────────────────────────────────
# CACHE EM DISCO (evita chamadas duplicadas)
# ─────────────────────────────────────────────
def _cache_key(prompt: str) -> str:
    return hashlib.md5(prompt.encode("utf-8")).hexdigest()

def _load_cache(prompt: str) -> Optional[str]:
    f = CACHE_DIR / f"{_cache_key(prompt)}.json"
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
            if time.time() - data.get("ts", 0) < 7*24*3600:  # 7 dias
                log.info(f"♻️ Cache HIT: {data.get('titulo','')[:40]}...")
                return data["content"]
        except: pass
    return None

def _save_cache(prompt: str, content: str, titulo: str):
    try:
        f = CACHE_DIR / f"{_cache_key(prompt)}.json"
        with open(f, "w", encoding="utf-8") as file:
            json.dump({"content": content, "titulo": titulo, "ts": time.time()}, file, ensure_ascii=False)
        log.info(f"💾 Cache SAVE: {titulo[:40]}...")
    except: pass

# ─────────────────────────────────────────────
# MÓDULO RSS
# ─────────────────────────────────────────────
def buscar_noticias(feeds: list, keywords: list) -> list:
    encontradas = []
    for url in feeds:
        log.info(f"📡 Feed: {url}")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                titulo = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not titulo or not link: continue
                if any(kw in titulo.lower() for kw in keywords):
                    encontradas.append({"titulo": titulo, "link": link, "fonte": feed.feed.get("title", url)})
                    log.info(f"   ✅ {titulo[:60]}")
        except Exception as e:
            log.error(f"❌ Erro no feed {url}: {e}")
    log.info(f"📊 Total relevante: {len(encontradas)}")
    return encontradas

def _hash(link: str) -> str: return hashlib.md5(link.encode()).hexdigest()
def carregar_historico(arq: Path) -> set:
    if not arq.exists(): arq.touch(); return set()
    with open(arq, "r", encoding="utf-8") as f: return {l.strip() for l in f if l.strip()}
def salvar_historico(arq: Path, h: str):
    with open(arq, "a", encoding="utf-8") as f: f.write(h + "\n")
def filtrar_novas(noticias: list, historico: set) -> list:
    novas = []
    for n in noticias:
        h = _hash(n["link"])
        if h not in historico: n["hash"] = h; novas.append(n)
    log.info(f"🆕 Novas após dedup: {len(novas)}")
    return novas

# ─────────────────────────────────────────────
# MÓDULO PEXELS
# ─────────────────────────────────────────────
def buscar_imagem_pexels(categoria: str) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        log.warning("⚠️ PEXELS_API_KEY ausente. Fallback ativo.")
        return PEXELS_FALLBACK
    query = PEXELS_QUERY_MAP.get(categoria, PEXELS_QUERY_MAP["Finanças"])
    endpoint = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=3&orientation=landscape"
    try:
        req = urllib.request.Request(endpoint, headers={"Authorization": api_key, "User-Agent": PEXELS_USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        fotos = data.get("photos", [])
        if not fotos: return PEXELS_FALLBACK
        foto = fotos[0]
        return {"url": foto["src"].get("large2x") or foto["src"]["original"], "alt": (foto.get("alt") or f"{categoria} — FinacePro").strip()}
    except Exception as e:
        log.warning(f"⚠️ Pexels erro: {e}. Fallback ativo.")
        return PEXELS_FALLBACK

# ─────────────────────────────────────────────
# MÓDULO GEMINI [v4.5: Anti-429 + Cache]
# ─────────────────────────────────────────────
def configurar_gemini():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key: log.critical("❌ GEMINI_API_KEY não encontrada!"); sys.exit(1)
    client = genai.Client(api_key=api_key)
    log.info(f"🤖 Gemini OK. Modelo: {GEMINI_MODEL} | Tier: {'FREE (1 post/dia)' if IS_FREE_TIER else 'PAGO'}")
    return client

def gerar_artigo(client, titulo: str, fonte: str, categoria: str) -> Optional[str]:
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    ano_atual = datetime.now().year
    kw = KEYWORD_PRIMARIA.get(categoria, "finanças para MEI")
    prompt = f"""Você é jornalista financeiro sênior especializado em MEI. NOTÍCIA: "{titulo}" (fonte: {fonte}). KEYWORD: "{kw}". DATA: {data_hoje}.
[ESCREVA EM MARKDOWN]
# [Título com número + benefício + keyword | ex: "7 Melhores Cartões de Crédito para MEI em {ano_atual}"]
Meta description: [150-160 caracteres: keyword + benefício + CTA]
Tempo: X min | Atualizado: {data_hoje}
## Por Que Todo MEI Precisa Saber Disso
[2 parágrafos com dado do Banco Central/Sebrae. Use "{kw}" na 1ª frase.]
## [Benefício em números]
[3 parágrafos: comparativo de taxas, % de economia, critérios de aprovação.]
## Como Conquistar na Prática
1. [Ação]
2. [Ação]
3. [Ação]
4. [Ação]
5. [Ação]
## 3 Erros Que Custam Dinheiro
[3 parágrafos: erro + como evitar + fintech que resolve (Nubank PJ, Inter, C6, Mercado Pago).]
## Comparativo: Melhores Opções em {ano_atual}
| Instituição | Anuidade | Limite | Cashback | Melhor Para |
| --- | --- | --- | --- | --- |
| [Opção 1] | [valor] | [valor] | [%] | [perfil] |
| [Opção 2] | [valor] | [valor] | [%] | [perfil] |
| [Opção 3] | [valor] | [valor] | [%] | [perfil] |
| [Opção 4] | [valor] | [valor] | [%] | [perfil] |
## Conclusão
[1 parágrafo direto + CTA interno.]
## FAQ
P: Qual o melhor {kw} em {ano_atual}? R: [2-3 frases]
P: MEI negativado consegue crédito? R: [2-3 frases]
P: Como aumentar limite sendo MEI? R: [2-3 frases]
P: Conta PJ ou MEI para crédito? R: [2-3 frases]
Conteúdo por Conselho Editorial FinacePro em {data_hoje}. Caráter educativo.
═══ REGRAS ═══
- Português BR, nível médio
- "{kw}" aparece 4-6x
- Apenas dados verificáveis ("conforme Banco Central")
- Nada antes do # do título
- 950-1300 palavras
- Tabela com 4 linhas OBRIGATÓRIA"""

    # ✅ VERIFICA CACHE ANTES DE CHAMAR API
    cached = _load_cache(prompt)
    if cached: return cached

    for tent in range(1, GEMINI_MAX_TENTATIVAS + 1):
        try:
            log.info(f"🧠 Tentativa {tent}/{GEMINI_MAX_TENTATIVAS}: '{titulo[:50]}...'")
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            conteudo = resp.text.strip()
            log.info(f"✅ Artigo gerado ({len(conteudo)} chars)")
            _save_cache(prompt, conteudo, titulo)  # ✅ SALVA NO CACHE
            return conteudo
        except Exception as e:
            erro = str(e)
            # ✅ DETECTA SE É COTA DIÁRIA (429 com mensagem específica)
            if "429" in erro or "RESOURCE_EXHAUSTED" in erro:
                if IS_FREE_TIER and tent == 1:
                    # ✅ FREE TIER: após 1 falha, para para não gastar quota à toa
                    log.warning(f"⚠️ Free tier: cota provavelmente esgotada. Parando para evitar waste.")
                    return None
                # PAGO ou nova tentativa: backoff
                match = re.search(r"retry[_ ]in[_ ](\d+)", erro, re.I)
                espera = (int(match.group(1)) + 10) if match else (30 * (2 ** (tent-1)))
                if tent < GEMINI_MAX_TENTATIVAS:
                    log.warning(f"⏳ Rate limit. Aguardando {espera}s (tent {tent+1}/{GEMINI_MAX_TENTATIVAS})...")
                    time.sleep(espera)
                else:
                    log.error("❌ Cota esgotada. Post adiado para amanhã.")
                    return None
            else:
                log.error(f"❌ Erro não-retry: {e}")
                return None
    return None

# ─────────────────────────────────────────────
# MÓDULO HUGO
# ─────────────────────────────────────────────
def extrair_h1(md: str) -> str:
    for l in md.splitlines():
        if l.startswith("# "): return l[2:].strip()
    return "Artigo sobre Finanças para MEI"

def extrair_meta(md: str, titulo: str) -> str:
    for l in md.splitlines():
        if l.strip().startswith("Meta description:"):
            d = l.replace("Meta description:", "").strip()
            if len(d) > 50: return d[:160]
    return f"Guia: {titulo[:70]}. Dicas para MEI sobre crédito e finanças."[:160]

def slugify(t: str) -> str:
    s = t.lower()
    for a,b in {"á":"a","à":"a","ã":"a","â":"a","é":"e","ê":"e","í":"i","ó":"o","ô":"o","ú":"u","ç":"c"}.items(): s = s.replace(a,b)
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    return re.sub(r"[\s_]+", "-", s).strip("-")[:80]

def detectar_meta(titulo: str) -> tuple:
    tl = titulo.lower()
    cat, tags = "Finanças", []
    if any(k in tl for k in ["cartão","cartao","crédito","credito"]): cat = "Cartão de Crédito"; tags += ["cartão de crédito","crédito"]
    if any(k in tl for k in ["mei","microempreendedor"]): 
        if cat == "Finanças": cat = "MEI"
        tags += ["mei","empreendedorismo"]
    if any(k in tl for k in ["empréstimo","emprestimo","financiamento"]):
        if cat == "Finanças": cat = "Empréstimos"
        tags += ["empréstimo","crédito empresarial"]
    return cat, list(dict.fromkeys(tags or ["finanças","brasil"]))

def front_matter(titulo, cat, tags, img, meta):
    data = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    tags_y = "\n ".join(f'  - "{t}"' for t in tags)
    return f'''---
title: "{titulo.replace('"', "'")}"
date: {data}
draft: false
author: "Conselho Editorial FinacePro"
categories:
  - "{cat}"
tags:
{tags_y}
keywords: "{", ".join(tags[:5])}"
description: "{meta.replace('"', "'")}"
cover:
  image: "{img['url']}"
  alt: "{img['alt'].replace('"', "'")}"
  caption: "Crédito: Pexels"
  relative: false
  hidden: false
ShowToc: true
TocOpen: false
---

'''

def limpar_corpo(md: str) -> str:
    return "\n".join(l for l in md.splitlines() if not l.strip().startswith("# ") and not l.strip().startswith("Meta description:")).strip()

def salvar_post(conteudo, pasta, img):
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        titulo = extrair_h1(conteudo)
        cat, tags = detectar_meta(titulo)
        fm = front_matter(titulo, cat, tags, img, extrair_meta(conteudo, titulo))
        corpo = limpar_corpo(conteudo)
        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo)}.md"
        path = pasta / nome
        path.write_text(fm + corpo, encoding="utf-8")
        log.info(f"💾 Post salvo: {path}")
        return path
    except Exception as e:
        log.error(f"❌ Erro ao salvar: {e}")
        return None

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    log.info("="*60)
    log.info("🏦 BLOG AUTOMATOR v4.5 — Cartões de Crédito & MEI")
    log.info(f"📊 Tier: {'FREE (1 post/dia)' if IS_FREE_TIER else 'PAGO'}")
    log.info("="*60)
    
    client = configurar_gemini()
    log.info("\n📡 [1/4] Buscando notícias RSS...")
    noticias = buscar_noticias(RSS_FEEDS, KEYWORDS)
    if not noticias: log.warning("⚠️ Nenhuma notícia. Encerrando."); sys.exit(0)

    log.info("\n🔍 [2/4] Filtrando duplicatas...")
    historico = carregar_historico(HISTORICO_FILE)
    novas = filtrar_novas(noticias, historico)
    if not novas: log.info("✅ Todas já publicadas."); sys.exit(0)

    log.info(f"\n✍️ [3/4] Gerando posts (máx: {MAX_POSTS})...")
    criados = 0
    for noticia in novas[:MAX_POSTS]:
        log.info(f"\n{'─'*50}")
        cat, _ = detectar_meta(noticia["titulo"])
        log.info("🖼️ Buscando imagem..."); img = buscar_imagem_pexels(cat)
        log.info(f"⏳ Pausa {PEXELS_DELAY}s..."); time.sleep(PEXELS_DELAY)
        log.info("🧠 Gerando artigo..."); artigo = gerar_artigo(client, noticia["titulo"], noticia["fonte"], cat)
        if artigo is None: continue
        path = salvar_post(artigo, CONTENT_DIR, img)
        if path: salvar_historico(HISTORICO_FILE, noticia["hash"]); criados += 1; log.info(f"✅ Post #{criados} criado!")
        if criados < MAX_POSTS: log.info(f"⏳ Pausa {API_DELAY}s..."); time.sleep(API_DELAY)

    log.info(f"\n🚀 [4/4] Finalizando ({criados} post(s))...")
    if criados == 0: log.warning("⚠️ Nenhum post criado. Workflow OK."); sys.exit(0)
    log.info(f"\n🎉 CONCLUÍDO! {criados} post(s) salvo(s).")

if __name__ == "__main__":
    main()
