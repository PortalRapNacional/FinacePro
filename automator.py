"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v6.2 — FinacePro [GROQ CLOUD]            ║
║   [FIX v6.2] Estrutura JSON (400 Fix) + Indentação + Pexels     ║
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

# ✅ CONFIGURAÇÃO GROQ (O cérebro mais rápido)
GROQ_MODEL = "llama3-8b-8192"
MAX_POSTS = 1 
API_DELAY = 15 

PEXELS_QUERY_MAP = {
    "Cartão de Crédito": "credit card business finance",
    "MEI": "small business entrepreneur",
    "Empréstimos": "bank loan money finance",
    "Finanças": "personal finance investment money",
}
PEXELS_FALLBACK = {"url": "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg", "alt": "Finanças e crédito para empreendedores brasileiros"}
PEXELS_USER_AGENT = "Mozilla/5.0 (compatible; FinaceProBot/6.2;)"

KEYWORD_PRIMARIA = {
    "Cartão de Crédito": "cartão de crédito para MEI",
    "MEI": "MEI microempreendedor individual",
    "Empréstimos": "empréstimo para MEI",
    "Finanças": "educação financeira para empreendedores",
}

# ─────────────────────────────────────────────
# CACHE & UTILITÁRIOS
# ─────────────────────────────────────────────
def _cache_key(prompt: str) -> str: return hashlib.md5(prompt.encode("utf-8")).hexdigest()

def _load_cache(prompt: str) -> Optional[str]:
    f = CACHE_DIR / f"{_cache_key(prompt)}.json"
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
            log.info(f"♻️ Cache HIT: {data.get('titulo','')[:40]}...")
            return data["content"]
        except: pass
    return None

def _save_cache(prompt: str, content: str, titulo: str):
    try:
        f = CACHE_DIR / f"{_cache_key(prompt)}.json"
        with open(f, "w", encoding="utf-8") as file:
            json.dump({"content": content, "titulo": titulo, "ts": time.time()}, file, ensure_ascii=False)
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
        except: pass
    return encontradas

def _hash(link: str) -> str: return hashlib.md5(link.encode()).hexdigest()
def carregar_historico(arq: Path) -> set:
    if not arq.exists(): arq.touch(); return set()
    with open(arq, "r", encoding="utf-8") as f: return {l.strip() for l in f if l.strip()}
def salvar_historico(arq: Path, h: str):
    with open(arq, "a", encoding="utf-8") as f: f.write(h + "\n")

# ─────────────────────────────────────────────
# MÓDULO PEXELS
# ─────────────────────────────────────────────
def buscar_imagem_pexels(categoria: str) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key: return PEXELS_FALLBACK
    query = PEXELS_QUERY_MAP.get(categoria, PEXELS_QUERY_MAP["Finanças"])
    endpoint = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1"
    try:
        req = urllib.request.Request(endpoint, headers={"Authorization": api_key, "User-Agent": PEXELS_USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return {"url": data["photos"][0]["src"]["large2x"], "alt": data["photos"][0].get("alt", categoria)}
    except: return PEXELS_FALLBACK

# ─────────────────────────────────────────────
# MÓDULO IA (GROQ CLOUD API) - CORREÇÃO 400
# ─────────────────────────────────────────────
def gerar_artigo_groq(titulo: str, fonte: str, categoria: str) -> Optional[str]:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        log.critical("❌ GROQ_API_KEY não encontrada!"); return None

    data_hoje = datetime.now().strftime("%d/%m/%Y")
    kw = KEYWORD_PRIMARIA.get(categoria, "finanças para MEI")
    prompt = f"""Escreva um artigo técnico sobre: "{titulo}" (Fonte: {fonte}). 
    Keyword: {kw}. Use Markdown, H1, Meta description e uma Tabela de Comparação. 
    Mínimo 800 palavras."""

    cached = _load_cache(prompt)
    if cached: return cached

    # ✅ INDENTAÇÃO CORRIGIDA E HEADERS COMPLETOS
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "FinacePro/1.0"
    }

    # ✅ PAYLOAD EM FORMATO CHAT COMPLETION (Evita Erro 400)
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Você é um jornalista financeiro especializado em SEO e AdSense."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }

    try:
        log.info(f"🧠 Chamando Groq ({GROQ_MODEL})...")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", 
            data=json.dumps(payload).encode("utf-8"), 
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            conteudo = res['choices'][0]['message']['content'].strip()
            _save_cache(prompt, conteudo, titulo)
            return conteudo
    except urllib.error.HTTPError as e:
        detalhes = e.read().decode()
        log.error(f"❌ Erro 400 da Groq: {detalhes}")
        return None
    except Exception as e:
        log.error(f"❌ Erro inesperado: {e}"); return None

# ─────────────────────────────────────────────
# MÓDULO HUGO & SAVING
# ─────────────────────────────────────────────
def slugify(t: str) -> str:
    s = t.lower()
    for a,b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ã":"a","ç":"c"}.items(): s = s.replace(a,b)
    return re.sub(r"[\s_]+", "-", re.sub(r"[^a-z0-9\s-]", "", s)).strip("-")

def salvar_post(conteudo, img):
    try:
        linhas = conteudo.splitlines()
        titulo_h1 = next((l[2:].strip() for l in linhas if l.startswith("# ")), "Artigo FinacePro")
        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo_h1)}.md"
        
        fm = f'''---
title: "{titulo_h1.replace('"', "'")}"
date: {datetime.now(timezone.utc).isoformat()}
author: "Conselho Editorial FinacePro"
cover:
  image: "{img['url']}"
---

'''
        (CONTENT_DIR / nome).write_text(fm + conteudo, encoding="utf-8")
        return nome
    except Exception as e:
        log.error(f"❌ Erro ao salvar: {e}"); return None

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    log.info("🚀 FinacePro v6.2 [GROQ STABLE]")
    noticias = buscar_noticias(RSS_FEEDS, KEYWORDS)
    historico = carregar_historico(HISTORICO_FILE)
    novas = [n for n in noticias if _hash(n["link"]) not in historico]

    if not novas:
        log.info("✅ Tudo atualizado."); return

    for n in novas[:MAX_POSTS]:
        img = buscar_imagem_pexels("Finanças")
        artigo = gerar_artigo_groq(n["titulo"], n["fonte"], "Finanças")
        if artigo and salvar_post(artigo, img):
            salvar_historico(HISTORICO_FILE, _hash(n["link"]))
            log.info(f"✅ Sucesso: {n['titulo'][:40]}")
            break 

if __name__ == "__main__":
    main()
