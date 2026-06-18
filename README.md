# Search Scraper

Web app for getting organic Google search results. Enter a query — get up to 10 results, exportable as JSON or CSV.

## Stack

- **Backend:** Python 3.11, FastAPI, SerpAPI
- **Frontend:** Vanilla HTML/CSS/JS
- **Tests:** pytest
- **Deploy:** Docker + docker-compose + Caddy

## Local run

```bash
cp .env.example .env
# Add your SERPAPI_KEY to .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000

## Run via Docker

```bash
# Create .env first with your SERPAPI_KEY
docker-compose up -d --build
```

## Run tests

```bash
pytest tests/ -v
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SERPAPI_KEY` | — | Required. Get at serpapi.com |
| `ALLOWED_ORIGIN` | `*` | Set your domain in production |
| `RATE_LIMIT_REQUESTS` | `10` | Max requests per IP per window |
| `RATE_LIMIT_WINDOW` | `60` | Window size in seconds |

## Security

| Area | Measure |
|---|---|
| XSS | DOM API only, no innerHTML with user data |
| Input validation | sanitize_query() — length, control chars, URL scheme |
| Rate limiting | Max 10 req / 60s per IP (configurable) |
| Security headers | CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy |
| CORS | Configurable ALLOWED_ORIGIN |
| Docker | Non-root user, no-new-privileges, read-only filesystem |

## Export formats

- **JSON** — `results_<query>.json`
- **CSV** — `results_<query>.csv` (UTF-8 BOM for Excel)
