# Briefly — AI Article Summarizer

A responsive HTML/CSS/JavaScript interface with a Vercel Python API. The backend extracts readable article text and uses a LangChain agent with an OpenRouter-hosted `openai/gpt-4o-mini` model to summarize public news/blog URLs. Users can download the result as TXT or PDF.

## Deploy to Vercel

1. Create a new GitHub repository and upload these project files.
2. Import that repository at https://vercel.com/new.
3. In **Project → Settings → Environment Variables**, add:
   - Name: `OPENROUTER_API_KEY`
   - Value: your OpenRouter API key
   - Environments: Production (and Preview/Development if needed)
4. Redeploy after adding the variable.
5. Open the deployed URL and test with a public article URL.

## Run locally

Use Python 3.10+ and install dependencies:

```bash
pip install -r requirements.txt
```

Set `OPENROUTER_API_KEY` in your environment, then run the frontend with a static server and the Python API using Vercel CLI:

```bash
npm i -g vercel
vercel dev
```

## Notes

- The OpenRouter API key belongs in Vercel environment variables only; never place it in `app.js` or `index.html`.
- Some publishers block automated access, use dynamic pages, or require login/subscription. The app will show an error if it cannot extract enough readable text.
- PDF download is generated in the browser; TXT download is also available.
- This is a summarization aid, not independent fact-checking. Verify important claims in the original article.
- Production hardening should add stricter DNS/IP-based SSRF protections, rate limiting, and request-size controls before exposing the endpoint to untrusted traffic.
