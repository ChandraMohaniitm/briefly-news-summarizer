import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI


def valid_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc) and not parsed.username and not parsed.password
    except Exception:
        return False


def extract_article(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BrieflySummarizer/1.0; +https://vercel.com)"
    }
    response = requests.get(url, headers=headers, timeout=18, allow_redirects=True)
    response.raise_for_status()
    if not valid_public_url(response.url):
        raise ValueError("The page redirected to an unsupported URL.")
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    # Prefer semantic article content, then main, then body.
    container = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = []
    for node in container.find_all(["p", "h1", "h2", "h3", "li"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        if len(text) >= 35 and text not in paragraphs:
            paragraphs.append(text)
    content = "\n".join(paragraphs)
    if len(content) < 250:
        content = re.sub(r"\s+", " ", container.get_text(" ", strip=True))
    content = content[:18000]
    if len(content.strip()) < 180:
        raise ValueError("Not enough readable text was found. This site may block automated access or require a login.")
    return title or urlparse(url).netloc, content


def process_request(request):
    if request.method != "POST":
        return _response(405, {"error": "Use POST to summarize an article."})
    try:
        body = request.get_json()
        if not isinstance(body, dict):
            return _response(400, {"error": "Please provide an article URL."})
        url = str(body.get("url", "")).strip()
        if not valid_public_url(url):
            return _response(400, {"error": "Enter a valid public http:// or https:// article URL."})

        # Basic SSRF guard: reject local/private hostnames and IPs.
        host = urlparse(url).hostname or ""
        if host.lower() in ("localhost", "127.0.0.1", "::1") or host.lower().endswith((".local", ".internal")):
            return _response(400, {"error": "Private or local URLs are not supported."})

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return _response(500, {"error": "Server setup is incomplete: add OPENROUTER_API_KEY in Vercel Environment Variables."})

        title, article_text = extract_article(url)
        length = body.get("length", "medium")
        style = body.get("style", "simple")
        length_instructions = {
            "short": "Use 3–5 concise bullet points and one short overall takeaway.",
            "medium": "Write a clear overview, 5–8 key takeaways, and a one-sentence bottom line.",
            "detailed": "Write a more detailed overview, 8–12 key takeaways, important names/numbers/dates, and a bottom line."
        }.get(length, "Write a clear overview, 5–8 key takeaways, and a one-sentence bottom line.")
        style_instructions = {
            "simple": "Use simple, plain English that a general reader can understand.",
            "professional": "Use a concise, professional editorial tone.",
            "student": "Explain in student-friendly language and briefly clarify technical terms."
        }.get(style, "Use simple, plain English that a general reader can understand.")

        @tool
        def fetch_news(article_url: str) -> str:
            """Fetch and extract the main readable text from a public news article or blog URL."""
            if article_url != url:
                return "Only summarize the URL supplied by the user for this request."
            return f"TITLE: {title}\nSOURCE URL: {url}\nARTICLE TEXT:\n{article_text}"

        llm = ChatOpenAI(
            model="openai/gpt-4o-mini",
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            max_tokens=1400,
        )
        agent = create_agent(
            model=llm,
            tools=[fetch_news],
            system_prompt=(
                "You are Briefly, an accurate news and blog summarization agent. "
                "Use the fetch_news tool to read the supplied article before summarizing. "
                "Summarize only what is supported by the source. Do not invent facts, quotes, context, or numbers. "
                "If the article contains multiple distinct stories, summarize each separately. "
                "Clearly separate Overview, Key Takeaways, and Bottom Line. "
                "Mention uncertainty or missing context instead of guessing. "
                f"{length_instructions} {style_instructions} "
                "Return clean Markdown. Do not claim to have verified facts independently."
            ),
        )
        result = agent.invoke({
            "messages": [{
                "role": "user",
                "content": f"Use fetch_news to read and summarize this article URL: {url}"
            }]
        })
        messages = result.get("messages", [])
        summary = ""
        for message in reversed(messages):
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                # Skip raw tool output; return the final assistant answer.
                if getattr(message, "type", "") == "ai":
                    summary = content.strip()
                    break
        if not summary:
            raise RuntimeError("The AI agent did not return a summary.")
        return _response(200, {"title": title, "url": url, "summary": summary})
    except requests.exceptions.Timeout:
        return _response(504, {"error": "The article site took too long to respond. Try again or use another link."})
    except requests.exceptions.RequestException:
        return _response(422, {"error": "Could not access this article. The site may block automated requests or require a login."})
    except ValueError as exc:
        return _response(422, {"error": str(exc)})
    except Exception as exc:
        print("Summarizer error:", repr(exc))
        return _response(500, {"error": "Summary generation failed. Check the Vercel function logs and your OpenRouter API key/model access."})


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        class RequestAdapter:
            method = "POST"
            def get_json(self_inner):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    return None
        result = process_request(RequestAdapter())
        self.send_response(result.get("statusCode", 500))
        for key, value in result.get("headers", {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(result.get("body", "{}").encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        self.send_response(405)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"Use POST to summarize an article."}')


def _response(status, payload):
    # Vercel's Python runtime accepts a dictionary return from the handler.
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-store"
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }
