"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v9.0 — FinacePro [ELITE PRODUCTION]      ║
║   [FINAL] Auto-Categorização + Random Pexels + Editorial Clean  ║
╚══════════════════════════════════════════════════════════════════╝
"""
import os, re, sys, time, hashlib, logging, json, urllib.request, urllib.parse, urllib.error, random
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
    "empréstimo", "emprestimo", "financiamento", "limite de crédito",
    "fintechs", "conta pj", "crédito empresarial", "cartão mei",
    "taxa de juros", "score serasa", "antecipação recebíveis",
]

CONTENT_DIR = Path("content/posts")
HISTORICO_FILE = Path("historico.txt")
CACHE_DIR = Path(".ai_cache")
CACHE_DIR.mkdir(exist_ok=True)

GROQ_MODEL = "llama-3.1-8b-instant"
MAX_POSTS = 1 
API_DELAY = 15 

PEXELS_QUERY_MAP = {
    "Cartão de Crédito": "credit card business finance",
    "MEI": "entrepreneur small business",
    "Empréstimos": "bank loan money",
    "Finanças": "personal finance wealth",
}
PEXELS_FALLBACK = {"url": "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg", "alt": "FinacePro Finanças"}

# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────
def _hash(link: str) -> str: return hashlib.md5(link.encode()).hexdigest()

def _load_cache(prompt: str) -> Optional[str]:
    f = CACHE_DIR / f"{hashlib.md5(prompt.encode()).hexdigest()}.json"
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as file:
                return json.load(file)["content"]
        except: pass
    return None

def _save_cache(prompt: str, content: str, titulo: str):
    f = CACHE_DIR / f"{hashlib.md5(prompt.encode()).hexdigest()}.json"
    with open(f, "w", encoding="utf-8") as file:
        json.dump({"content": content, "titulo": titulo, "ts": time.time()}, file, ensure_ascii=False)

def slugify(t: str) -> str:
    s = t.lower()
    for a,b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ã":"a","ç":"c"}.items(): s = s.replace(a,b)
    return re.sub(r"[\s_]+", "-", re.sub(r"[^a-z0-9\s-]", "", s)).strip("-")

# ─────────────────────────────────────────────
# MÓDULO PEXELS (RANDOMIZADO)
# ─────────────────────────────────────────────
def buscar_imagem_pexels(categoria: str) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key: return PEXELS_FALLBACK
    
    query = PEXELS_QUERY_MAP.get(categoria, "business finance")
    rand_page = random.randint(1, 80)
    endpoint = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&page={rand_page}"
    
    try:
        log.info(f"🖼️ Buscando imagem única no Pexels (Pág {rand_page})...")
        req = urllib.request.Request(endpoint, headers={"Authorization": api_key, "User-Agent": "FinacePro/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("photos"):
                return {"url": data["photos"][0]["src"]["large2x"], "alt": data["photos"][0].get("alt", categoria)}
        return PEXELS_FALLBACK
    except: return PEXELS_FALLBACK

# ─────────────────────────────────────────────
# MÓDULO IA (GROQ)
# ─────────────────────────────────────────────
def gerar_artigo_groq(titulo: str, fonte: str) -> Optional[str]:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key: return None

    prompt = f"""Escreva um artigo de 800 palavras sobre: "{titulo}".
    DIRETRIZES:
    1. Comece DIRETO com o título em H1 (Ex: # Título do Post).
    2. NUNCA use 'Título:', 'Meta descrição:', 'Introdução:'.
    3. Use subtítulos H2 e H3 e crie uma TABELA comparativa em Markdown.
    4. Estilo: Jornalismo de Elite (Bloomberg/Exame)."""

    cached = _load_cache(prompt)
    if cached: return cached

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Você é o Conselho Editorial do FinacePro. Seu texto é profissional e focado em SEO Financeiro."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.65
    }

    try:
        log.info(f"🧠 Gerando conteúdo via Groq...")
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            conteudo = res['choices'][0]['message']['content'].strip()
            _save_cache(prompt, conteudo, titulo)
            return conteudo
    except Exception as e:
        log.error(f"❌ Erro Groq: {e}"); return None

# ─────────────────────────────────────────────
# SALVAMENTO EDITORIAL (AUTO-CATEGORIA)
# ─────────────────────────────────────────────
def salvar_post(conteudo, img):
    try:
        linhas = conteudo.splitlines()
        corpo_filtrado = []
        for l in linhas:
            if any(term in l.lower() for term in ["título:", "meta descrição:", "introdução:", "resumo:"]):
                continue
            corpo_filtrado.append(l)
        
        texto_limpo = "\n".join(corpo_filtrado).strip()
        
        # ✅ Lógica de Categorização Automática
        categoria = "Finanças"
        texto_para_analise = texto_limpo.lower()
        if any(x in texto_para_analise for x in ["cartão", "cartao", "anuidade", "limite"]):
            categoria = "Cartões"
        elif any(x in texto_para_analise for x in ["mei", "microempreendedor", "pj", "empresa"]):
            categoria = "MEI"
        elif any(x in texto_para_analise for x in ["empréstimo", "financiamento", "taxa", "juros"]):
            categoria = "Empréstimos"

        titulo_h1 = next((l[2:].strip() for l in corpo_filtrado if l.startswith("# ")), "Destaque Financeiro")
        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo_h1)}.md"
        
        # Frontmatter com Categorias e Tags automáticas
        fm = f'''---
title: "{titulo_h1}"
date: {datetime.now(timezone.utc).isoformat()}
categories: ["{categoria}"]
tags: ["{categoria}", "FinacePro", "Crédito"]
author: "Editorial FinacePro"
cover:
  image: "{img["url"]}"
---

'''
        (CONTENT_DIR / nome).write_text(fm + texto_limpo, encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"❌ Erro salvar_post: {e}"); return False

def main():
    log.info("🚀 FinacePro v9.0 [ELITE] Iniciado")
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORICO_FILE.exists(): HISTORICO_FILE.touch()
    
    with open(HISTORICO_FILE, "r") as f: historico = {l.strip() for l in f}

    noticias = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if any(kw in entry.title.lower() for kw in KEYWORDS):
                    if _hash(entry.link) not in historico:
                        noticias.append(entry)
        except: continue

    if not noticias:
        log.info("✅ Tudo atualizado."); return

    for n in noticias[:MAX_POSTS]:
        # Define busca de imagem baseada na keyword encontrada
        cat_busca = "Finanças"
        if "cartão" in n.title.lower(): cat_busca = "Cartão de Crédito"
        elif "mei" in n.title.lower(): cat_busca = "MEI"
        elif "empréstimo" in n.title.lower(): cat_busca = "Empréstimos"

        img = buscar_imagem_pexels(cat_busca)
        artigo = gerar_artigo_groq(n.title, n.link)
        if artigo and salvar_post(artigo, img):
            with open(HISTORICO_FILE, "a") as f: f.write(_hash(n.link) + "\n")
            log.info(f"✅ Artigo Publicado na categoria {cat_busca}!")
            break

if __name__ == "__main__":
    main()
