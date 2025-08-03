from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
from dotenv import load_dotenv
import openai
from fastapi.middleware.cors import CORSMiddleware
from newspaper import Article

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class NewsRequest(BaseModel):
    text: str

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
GNEWS_ENDPOINT = "https://gnews.io/api/v4/search"
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def extract_text_from_url(url: str) -> str:
    try:
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.strip()
        return text
    except Exception:
        return ""

def search_gnews(query):
    params = {
        "q": query,
        "lang": "es",
        "max": 10,
        "token": GNEWS_API_KEY
    }
    results = []
    try:
        response = requests.get(GNEWS_ENDPOINT, params=params)
        if response.status_code == 200:
            data = response.json()
            results = [
                {"title": article["title"], "url": article["url"]}
                for article in data.get("articles", [])
            ]
    except Exception:
        pass
    return results

def search_newsapi(query):
    params = {
        "q": query,
        "language": "es",
        "pageSize": 10,
        "apiKey": NEWSAPI_KEY
    }
    results = []
    try:
        response = requests.get(NEWSAPI_ENDPOINT, params=params)
        if response.status_code == 200:
            data = response.json()
            results = [
                {"title": article["title"], "url": article["url"]}
                for article in data.get("articles", [])
            ]
    except Exception:
        pass
    return results

@app.post("/verify")
def verify_news(news: NewsRequest):
    query = news.text.strip()
    sources = []
    noticia_texto = query

    # Si el usuario pone un enlace
    if query.startswith("http://") or query.startswith("https://"):
        # 1. Scraping
        scraped_text = extract_text_from_url(query)
        noticia_texto = scraped_text if scraped_text else query
        sources.append({
            "title": "Fuente directa proporcionada por el usuario",
            "url": query
        })

        # 2. Buscar en GNews y NewsAPI.org usando el texto extraído o el enlace
        search_query = scraped_text if scraped_text else query
        sources += search_gnews(search_query)
        sources += search_newsapi(search_query)
    else:
        # Caso tradicional: texto de noticia
        sources = search_gnews(query)
        sources += search_newsapi(query)
        noticia_texto = query

    # Elimina duplicados por URL
    seen_urls = set()
    unique_sources = []
    for src in sources:
        if src["url"] not in seen_urls:
            unique_sources.append(src)
            seen_urls.add(src["url"])
    sources = unique_sources

    fuentes_str = "\n".join([f"- {item['title']} ({item['url']})" for item in sources]) or "No se encontraron fuentes."

    prompt = (
        f"Eres un verificador profesional de noticias, experto científico y periodista riguroso. "
        f"Debes analizar, con máxima objetividad y escepticismo, la siguiente noticia, titular, texto o enlace:\n"
        f"{noticia_texto}\n\n"
        f"Fuentes encontradas en medios online relevantes:\n{fuentes_str}\n\n"
        f"INSTRUCCIONES ESTRICTAS:\n"
        f"- Lee y analiza cuidadosamente las fuentes proporcionadas. Si alguna fuente oficial (gobierno, universidades, organismos internacionales, revistas científicas reconocidas) o fuentes científicas confiables confirman la noticia de forma clara y directa, responde 100% veracidad.\n"
        f"- Si la mayoría de las fuentes confiables rechazan, desmienten o refutan la noticia, responde 0% veracidad.\n"
        f"- Si las fuentes son mixtas, contradictorias, poco fiables, o no hay consenso, responde un porcentaje entre 10% y 50% (según la evidencia que pese más) y razona detalladamente las dudas.\n"
        f"- Si no se encuentra nada relevante, responde 20% o menos, y explica la incertidumbre y el peligro de confiar en información no respaldada.\n"
        f"- El porcentaje y la explicación deben estar SIEMPRE de acuerdo: nunca pongas 100% si la noticia es falsa o dudosa, ni 0% si la noticia es verdadera.\n"
        f"- Para temas científicos, usa consensos de la ciencia y literatura revisada por pares. Para temas políticos/sociales, prioriza fuentes oficiales y contrastadas.\n"
        f"- Si una fuente proporciona datos, cifras o declaraciones textuales, cítalos en la explicación.\n"
        f"- Prioriza la evidencia más fuerte y desestima rumores, opiniones sin base o fuentes poco fiables.\n"
        f"- Si existe desinformación previa sobre el tema, advierte sobre ella.\n"
        f"\n"
        f"EN TU EXPLICACIÓN:\n"
        f"- Haz un análisis profesional y estructurado, como haría un fact-checker experto o científico.\n"
        f"- Si la noticia es falsa o refutada, explica en detalle *por qué* es falsa, apoyándote en fuentes científicas, ejemplos históricos, consensos académicos y argumentos lógicos.\n"
        f"- Si existen pruebas o experimentos científicos relevantes, descríbelos brevemente (ejemplo: ‘Los experimentos de Eratóstenes y la fotografía satelital demuestran que la Tierra es redonda’).\n"
        f"- Si hay fuentes a favor y en contra, expón ambos puntos y especifica cuál tiene mayor evidencia y por qué.\n"
        f"- Si la noticia es verdadera pero matizable, especifica límites, contexto y advertencias.\n"
        f"- Si no hay información científica suficiente, indícalo y sugiere métodos para comprobarlo (experimentos, búsqueda de fuentes oficiales, contacto con expertos, etc).\n"
        f"\n"
        f"FORMATO DE RESPUESTA (sin añadir nada extra, sin conclusiones fuera de este formato):\n"
        f"Porcentaje de veracidad: XX%\n"
        f"Explicación: ...\n"
        f"Fuentes usadas:\n"
        f"- ...\n"
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un experto verificador de noticias. Debes dar un razonamiento claro, imparcial y basado en evidencia científica y fuentes periodísticas."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=700
        )
        analysis = completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar OpenAI: {str(e)}")

    return {
        "sources": sources,
        "openai_analysis": analysis
    }
