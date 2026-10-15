import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

load_dotenv()
app = FastAPI(title="Briefly AI News Summarizer")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Briefly — AI Summarizer</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:#0b1120;color:#eef2ff;font-family:Arial,sans-serif;display:grid;place-items:center;padding:24px}
main{width:100%;max-width:760px}.brand{text-align:center;font-size:48px;font-weight:800;margin:0}.brand span{color:#818cf8}
.sub{text-align:center;color:#a5b4fc;margin:12px 0 30px;line-height:1.6}
form{display:flex;gap:10px;padding:8px;border:1px solid #334155;background:#172033;border-radius:14px}
input{flex:1;min-width:0;padding:14px;border:0;outline:0;background:transparent;color:white;font-size:15px}
button{border:0;border-radius:10px;background:#6366f1;color:white;padding:14px 18px;font-weight:bold;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}#status{min-height:24px;text-align:center;color:#fbbf24;margin:18px 0}
article{display:none;margin-top:22px;padding:24px;background:#172033;border:1px solid #334155;border-radius:14px;line-height:1.75;overflow-wrap:anywhere}
article h2{margin-top:0;color:#a5b4fc}#summary{white-space:pre-wrap}
.note{text-align:center;color:#94a3b8;font-size:12px;margin-top:24px}
@media(max-width:560px){.brand{font-size:40px}form{flex-direction:column}input{padding:14px}}
</style></head><body><main>
<h1 class="brand">Briefly<span>.</span></h1>
<p class="sub">Paste a news or blog URL. Get the key points in seconds.</p>
<form id="form"><input type="url" name="url" id="url" placeholder="https://example.com/article" required><button id="btn" type="submit">Summarize</button></form>
<p id="status" role="status"></p><article id="result"><h2>Article Summary</h2><div id="summary"></div></article>
<p class="note">AI summaries may omit details. Verify important information with the original article.</p></main>
<script>
const form=document.getElementById('form'),btn=document.getElementById('btn');
form.addEventListener('submit',async e=>{
 e.preventDefault();const status=document.getElementById('status'),result=document.getElementById('result'),summary=document.getElementById('summary');
 btn.disabled=true;btn.textContent='Summarizing...';status.textContent='Fetching article and asking AI...';result.style.display='none';summary.textContent='';
 try{const res=await fetch('/summarize',{method:'POST',body:new FormData(form)});const data=await res.json();if(!res.ok||data.error)throw new Error(data.error||'Request failed.');summary.textContent=data.summary;result.style.display='block';status.textContent='';}
 catch(err){status.textContent=err.message||'Something went wrong.'}
 finally{btn.disabled=false;btn.textContent='Summarize'}
});
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(PAGE)

@app.post("/summarize")
def summarize(url: str = Form(...)):
    url = url.strip()
    if not url.startswith(("https://", "http://")):
        return {"error": "Please enter a valid article URL starting with http:// or https://."}
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {"error": "OPENROUTER_API_KEY is missing. Add it to .env or hosting environment variables."}
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        article_text = soup.get_text(" ", strip=True)
        if len(article_text) < 100:
            return {"error": "Not enough article text found. This website may block automated access."}

        ai_response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-4o-mini",
                  "messages": [
                      {"role": "system", "content": "Summarize this article in plain English. Give a 2-3 sentence overview and 3-5 key takeaways as bullet points. Do not invent facts."},
                      {"role": "user", "content": article_text[:12000]}
                  ],
                  "temperature": 0.2},
            timeout=60
        )
        if not ai_response.ok:
            try:
                detail = ai_response.json().get("error", {}).get("message", "")
            except Exception:
                detail = ""
            return {"error": f"AI provider error ({ai_response.status_code}). {detail[:250] or 'Check API key, model availability, and credits.'}"}
        data = ai_response.json()
        summary = data["choices"][0]["message"]["content"]
        if not summary:
            return {"error": "The AI returned an empty summary. Please try again."}
        return {"summary": summary}
    except requests.Timeout:
        return {"error": "Request timed out. Try another article URL."}
    except requests.RequestException:
        return {"error": "Could not access the article. The website may block requests or be unavailable."}
    except (KeyError, IndexError, TypeError, ValueError):
        return {"error": "Unexpected AI response. Please try again."}
