"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v5.0 — FinacePro [OPENROUTER]            ║
║   [FIX v5.0] Anti-429: OpenRouter Free + Pexels + Hugo Logic    ║
╚══════════════════════════════════════════════════════════════════╝
"""
import os, re, sys, time, hashlib, logging, json, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import feedparser

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

KEYWORDS = [
    "cartão de crédito", "cartao de credito", "mei", "microempreendedor",
    "empréstimo", "emprestimo", "financiamento", "limite de crédito", "limite de credito",
    "fintechs", "conta pj", "crédito empresarial", "credito empresarial",
    "cartão mei", "crédito pj", "taxa de juros", "score serasa",
    "antecipação recebíveis", "liberação crédito", "aprovação cartão",
]

CONTENT_DIR = Path("content/posts")
HISTORICO_FILE = Path("historico.txt")
CACHE_DIR = Path(".ai_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ✅ CONFIGURAÇÃO OPENROUTER (MODELOS FREE)
# Opções: "meta-llama/llama-3.1-70b-instruct:free" ou "google/gemini-flash-1.5-exp:free"
AI_MODEL = "meta-llama/llama-3.1-70b-instruct:free"
MAX_POSTS = 1 # Recomendado para manter qualidade e evitar filtros de spam
API_DELAY = 30 
PEXELS_DELAY = 2

PEXELS_QUERY_MAP = {
    "Cartão de Crédito": "credit card business finance",
    "MEI": "small business entrepreneur",
    "Empréstimos": "bank loan money finance",
    "Finanças": "personal finance investment money",
}
PEXELS_FALLBACK = {"url": "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg", "alt": "Finanças e crédito para empreendedores brasileiros"}
PEXELS_USER_AGENT = "Mozilla/5.0 (compatible; FinaceProBot/5.0;)"

KEYWORD_PRIMARIA = {
    "Cartão de Crédito": "cartão de crédito para MEI",
    "MEI": "MEI microempreendedor individual",
    "Empréstimos": "empréstimo para MEI",
    "Finanças": "educação financeira para empreendedores",
}

# ─────────────────────────────────────────────
# CACHE EM DISCO
# ─────────────────────────────────────────────
def _cache_key(prompt: str) -> str:
    return hashlib.md5(prompt.encode("utf-8")).hexdigest()

def _load_cache(prompt: str) -> Optional[str]:
    f = CACHE_DIR / f"{_cache_key(prompt)}.json"
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
            if time.time() - data.get("ts", 0) < 7*24*3600:
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
# MÓDULOS RSS & HISTÓRICO
# ─────────────────────────────────────────────
def buscar_noticias(feeds: list, keywords: list) -> list:
    encontradas = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                titulo = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not titulo or not link: continue
                if any(kw in titulo.lower() for kw in keywords):
                    encontradas.append({"titulo": titulo, "link": link, "fonte": feed.feed.get("title", url)})
        except Exception as e:
            log.error(f"❌ Erro no feed {url}: {e}")
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
    return novas

# ─────────────────────────────────────────────
# MÓDULO PEXELS
# ─────────────────────────────────────────────
def buscar_imagem_pexels(categoria: str) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key: return PEXELS_FALLBACK
    query = PEXELS_QUERY_MAP.get(categoria, PEXELS_QUERY_MAP["Finanças"])
    endpoint = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
    try:
        req = urllib.request.Request(endpoint, headers={"Authorization": api_key, "User-Agent": PEXELS_USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        fotos = data.get("photos", [])
        if not fotos: return PEXELS_FALLBACK
        foto = fotos[0]
        return {"url": foto["src"]["large2x"], "alt": foto.get("alt", categoria)}
    except Exception as e:
        log.warning(f"⚠️ Pexels erro: {e}")
        return PEXELS_FALLBACK

# ─────────────────────────────────────────────
# MÓDULO IA (OPENROUTER FREE TIER)
# ─────────────────────────────────────────────
def gerar_artigo_ai(titulo: str, fonte: str, categoria: str) -> Optional[str]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        log.critical("❌ OPENROUTER_API_KEY não encontrada!")
        return None

    data_hoje = datetime.now().strftime("%d/%m/%Y")
    kw = KEYWORD_PRIMARIA.get(categoria, "finanças para MEI")
    prompt = f"""Você é jornalista financeiro sênior especializado em MEI. NOTÍCIA: "{titulo}" (fonte: {fonte}). KEYWORD: "{kw}". DATA: {data_hoje}.
[ESCREVA EM MARKDOWN]
# [Título chamativo com {kw}]
Meta description: [150-160 caracteres com CTA]
Tempo: 4 min | Atualizado: {data_hoje}
## Por Que Todo MEI Precisa Saber Disso
[2 parágrafos. Use "{kw}" na 1ª frase.]
## Detalhes Importantes
[3 parágrafos explicando taxas, prazos e regras conforme Banco Central.]
## Como Solicitar ou Aplicar
1. [Ação]
2. [Ação]
3. [Ação]
## Tabela de Comparação
| Banco/Fintech | Vantagem Principal | Nota |
| --- | --- | --- |
| Nubank PJ | Facilidade | 4.8 |
| Inter Empresas | Isenção de Taxas | 4.7 |
| C6 Bank | Limite Progressivo | 4.5 |
## Conclusão
[1 parágrafo direto.]
## FAQ
P: Como aumentar o limite? R: [Resposta curta]
Conteúdo por Conselho Editorial FinacePro em {data_hoje}.
═══ REGRAS ═══
- Português BR
- Texto entre 800 e 1000 palavras
- Use a Tabela Markdown"""

    cached = _load_cache(prompt)
    if cached: return cached

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://portalrapnacional.github.io/FinacePro/",
        "X-Title": "FinacePro Automator"
    }

    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        log.info(f"🧠 Chamando IA ({AI_MODEL})...")
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            res = json.loads(resp.read().decode())
            conteudo = res['choices'][0]['message']['content'].strip()
            _save_cache(prompt, conteudo, titulo)
            return conteudo
    except Exception as e:
        log.error(f"❌ Erro na IA: {e}")
        return None

# ─────────────────────────────────────────────
# MÓDULO HUGO & SLUG
# ─────────────────────────────────────────────
def slugify(t: str) -> str:
    s = t.lower()
    for a,b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ã":"a","ç":"c"}.items(): s = s.replace(a,b)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    return re.sub(r"[\s_]+", "-", s).strip("-")[:80]

def detectar_meta(titulo: str) -> tuple:
    tl = titulo.lower()
    if any(k in tl for k in ["cartão","cartao","crédito"]): return "Cartão de Crédito", ["cartão", "crédito"]
    if "mei" in tl: return "MEI", ["mei", "negócios"]
    return "Finanças", ["finanças", "brasil"]

def salvar_post(conteudo, img):
    try:
        linhas = conteudo.splitlines()
        titulo_h1 = next((l[2:].strip() for l in linhas if l.startswith("# ")), "Artigo FinacePro")
        cat, tags = detectar_meta(titulo_h1)
        meta = next((l.replace("Meta description:","").strip() for l in linhas if "Meta description:" in l), titulo_h1)
        
        fm = f'''---
title: "{titulo_h1.replace('"', "'")}"
date: {datetime.now(timezone.utc).isoformat()}
draft: false
author: "Conselho Editorial FinacePro"
categories: ["{cat}"]
tags: {tags}
description: "{meta[:160].replace('"', "'")}"
cover:
  image: "{img['url']}"
  alt: "{img['alt'].replace('"', "'")}"
---
'''
        corpo = "\n".join(l for l in linhas if not l.startswith("# ") and "Meta description:" not in l).strip()
        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo_h1)}.md"
        (CONTENT_DIR / nome).write_text(fm + "\n" + corpo, encoding="utf-8")
        return nome
    except Exception as e:
        log.error(f"❌ Erro ao salvar: {e}"); return None

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    log.info("🚀 Iniciando FinacePro v5.0")
    noticias = buscar_noticias(RSS_FEEDS, KEYWORDS)
    historico = carregar_historico(HISTORICO_FILE)
    novas = filtrar_novas(noticias, historico)

    if not novas:
        log.info("✅ Tudo atualizado."); return

    criados = 0
    for n in novas[:MAX_POSTS]:
        cat, _ = detectar_meta(n["titulo"])
        img = buscar_imagem_pexels(cat)
        artigo = gerar_artigo_ai(n["titulo"], n["fonte"], cat)
        if artigo:
            if salvar_post(artigo, img):
                salvar_historico(HISTORICO_FILE, n["hash"])
                criados += 1
                log.info(f"✅ Post criado: {n['titulo'][:40]}")
        if criados < MAX_POSTS: time.sleep(API_DELAY)

if __name__ == "__main__":
    main()
