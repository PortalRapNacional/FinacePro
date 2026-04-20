"""
╔══════════════════════════════════════════════════════════════════╗
║         BLOG AUTOMATOR v8.0 — FinacePro [ELITE EDITION]        ║
║   [FINAL] Random Pexels + Editorial Clean + AdSense Meta        ║
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
    "MEI": "small business entrepreneur",
    "Empréstimos": "bank loan money finance",
    "Finanças": "personal finance investment money",
}
PEXELS_FALLBACK = {"url": "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg", "alt": "Finanças FinacePro"}

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

# ─────────────────────────────────────────────
# MÓDULO PEXELS (CORREÇÃO: RANDOMIZADO)
# ─────────────────────────────────────────────
def buscar_imagem_pexels(categoria: str) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key: return PEXELS_FALLBACK
    
    query = PEXELS_QUERY_MAP.get(categoria, PEXELS_QUERY_MAP["Finanças"])
    # ✅ Randomiza a página para evitar imagens repetidas
    rand_page = random.randint(1, 50)
    endpoint = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&page={rand_page}"
    
    try:
        log.info(f"🖼️ Buscando imagem única no Pexels (Pág {rand_page})...")
        req = urllib.request.Request(endpoint, headers={"Authorization": api_key, "User-Agent": "FinacePro/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
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

    prompt = f"""Você é um analista financeiro sênior. Escreva um artigo de autoridade sobre: "{titulo}".
    REGRAS DE OURO:
    1. Comece DIRETO com um título H1 impactante (Não escreva 'Título:').
    2. Escreva uma introdução cativante sem rótulos.
    3. Use subtítulos H2 e H3 para organizar os dados.
    4. Crie uma TABELA DE COMPARAÇÃO em Markdown.
    5. Mínimo 800 palavras. Estilo: Bloomberg/Exame.
    6. Proibido rótulos como: 'Meta descrição:', 'Resumo:', 'Introdução:'.
    7. Foque em SEO para crédito e MEI."""

    cached = _load_cache(prompt)
    if cached: return cached

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Você é o Conselho Editorial do FinacePro. Tom profissional e direto."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }

    try:
        log.info(f"🧠 Gerando artigo via Groq...")
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            conteudo = res['choices'][0]['message']['content'].strip()
            _save_cache(prompt, conteudo, titulo)
            return conteudo
    except Exception as e:
        log.error(f"❌ Falha na IA: {e}"); return None

# ─────────────────────────────────────────────
# SALVAMENTO EDITORIAL (CORREÇÃO: LIMPEZA TOTAL)
# ─────────────────────────────────────────────
def slugify(t: str) -> str:
    s = t.lower()
    for a,b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ã":"a","ç":"c"}.items(): s = s.replace(a,b)
    return re.sub(r"[\s_]+", "-", re.sub(r"[^a-z0-9\s-]", "", s)).strip("-")

def salvar_post(conteudo, img):
    try:
        linhas = conteudo.splitlines()
        corpo_final = []
        for l in linhas:
            # ✅ Remove qualquer linha que pareça instrução de IA
            if any(term in l.lower() for term in ["título:", "meta descrição:", "introdução:", "meta description:", "resumo:", "fonte:"]):
                continue
            corpo_final.append(l)
        
        texto_limpo = "\n".join(corpo_final).strip()
        titulo_h1 = next((l[2:].strip() for l in corpo_final if l.startswith("# ")), "Inovação Financeira")
        
        nome = f"{datetime.now().strftime('%Y-%m-%d')}-{slugify(titulo_h1)}.md"
        fm = f'---\ntitle: "{titulo_h1}"\ndate: {datetime.now(timezone.utc).isoformat()}\nauthor: "Conselho Editorial FinacePro"\ncover:\n  image: "{img["url"]}"\n---\n\n'
        
        (CONTENT_DIR / nome).write_text(fm + texto_limpo, encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"❌ Erro ao salvar post: {e}"); return False

def main():
    log.info("🚀 FinacePro v8.0 [ELITE] Iniciado")
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

    criados = 0
    for n in noticias:
        if criados >= MAX_POSTS: break
        img = buscar_imagem_pexels("Finanças")
        artigo = gerar_artigo_groq(n.title, n.link)
        if artigo and salvar_post(artigo, img):
            with open(HISTORICO_FILE, "a") as f: f.write(_hash(n.link) + "\n")
            log.info(f"✅ Sucesso: {n.title[:50]}...")
            criados += 1
            if criados < MAX_POSTS: time.sleep(API_DELAY)

if __name__ == "__main__":
    main()
