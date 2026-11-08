# Quantix

> **Production-grade Model Context Protocol (MCP) server for SEC EDGAR company filings analysis.**  
> *Track what changed in public company filings with verified citations, multi-year XBRL financial trends, and automated 8-K alerts.*

---

## 🌟 What is Quantix? (Plain English)

If you follow 10 to 20 public stocks—whether you write a finance newsletter, host an investment YouTube channel, or manage your own portfolio—keeping up with SEC filings is overwhelming:
- Annual reports (**Form 10-K**) can stretch past 100 pages.
- Risk factor sections change quietly from year to year, burying critical warnings about lawsuits, tariffs, or supply chain bottlenecks.
- Financial websites often report adjusted numbers without citing the underlying SEC filing.

**Quantix connects your favorite AI assistant (Claude Desktop, Cursor, or any MCP client) directly to the official SEC EDGAR database.** Instead of reading 100-page PDFs or trusting third-party aggregators:
1. You ask: *"What changed in Apple's risk factors this year?"*
2. Quantix pulls both filings directly from the SEC, performs paragraph-by-paragraph comparison, finds newly added or removed disclosures, and has the AI summarize **what changed and why it matters**.
3. Every single fact, number, and diff is accompanied by a **direct link to the official SEC document**.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph Clients["MCP Clients"]
        Claude["Claude Desktop (stdio)"]
        Remote["Remote Web Client / IDE (Streamable HTTP)"]
    end

    subgraph QuantixServer["Quantix Server (FastMCP)"]
        Auth["Bearer Auth Middleware\n(for HTTP)"]
        Health["/health Endpoint"]
        Router["FastMCP Tool Router"]
        
        subgraph Services["Core Engine & Services"]
            Lookup["Company Lookup\n(Ticker to CIK)"]
            XBRL["XBRL Metrics Engine\n(Concept Fallbacks)"]
            Sections["Section Parser\n(TOC Filter + Regex)"]
            DiffEngine["Paragraph Diff\n(rapidfuzz Similarity)"]
            Briefing["Briefing Generator"]
            LLM["LLM Provider\n(Anthropic / OpenAI)"]
        end

        subgraph Background["Scheduled Alerting"]
            Scheduler["APScheduler Runner"]
            Telegram["Telegram Notifier"]
        end

        subgraph EdgarLayer["SEC EDGAR Client"]
            Limiter["Async Rate Limiter\n(8 req/sec Token Bucket)"]
            Retrier["Backoff Retrier\n(429 / 5xx Handling)"]
            Cache["aiosqlite Cache & DB\n(WAL Mode + TTL)"]
        end
    end

    subgraph SEC["Official SEC EDGAR API"]
        Tickers["sec.gov/company_tickers.json"]
        Submissions["data.sec.gov/submissions"]
        CompanyFacts["data.sec.gov/api/xbrl/companyfacts"]
        Archives["sec.gov/Archives/edgar/data/..."]
    end

    Clients -->|"MCP Protocol"| Auth
    Auth --> Router
    Router --> Services
    Services --> EdgarLayer
    EdgarLayer -->|"HTTPS Rate Limited"| SEC
    Scheduler --> Services
    Scheduler --> Telegram
    Telegram -->|"Telegram Bot API"| UserChat["Telegram Channel / DMs"]
```

---

## ⚡ Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager (`curl -LsSf https://astral.sh/uv/install.sh` or `winget install --id=astral-sh.uv`)

### 1. Clone & Configure
```bash
git clone https://github.com/your-org/quantix.git
cd quantix

# Copy environment template
cp .env.example .env
```

Edit `.env` to configure your settings:
```ini
# REQUIRED: Must be your application name and a valid contact email (SEC policy)
EDGAR_USER_AGENT=QuantixResearch analyst@example.com

# LLM Provider (Anthropic or OpenAI)
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=your_key_here

# MCP Transport ('stdio' for Claude Desktop, 'streamable-http' for remote deployment)
MCP_TRANSPORT=stdio
```

### 2. Install Dependencies
```bash
uv sync
```

### 3. Run Locally
```bash
# Starts the FastMCP server on stdio
uv run quantix
```

---

## 🖥️ Connecting to Claude Desktop (stdio mode)

To connect Quantix to Claude Desktop, edit your Claude Desktop configuration file:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add `quantix` under `mcpServers`:

```json
{
  "mcpServers": {
    "quantix": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/Quantix",
        "run",
        "quantix"
      ],
      "env": {
        "EDGAR_USER_AGENT": "QuantixApp your_email@example.com",
        "LLM_PROVIDER": "openai",
        "LLM_MODEL": "gpt-4o-mini",
        "OPENAI_API_KEY": "your_api_key_here",
        "DB_PATH": "/absolute/path/to/Quantix/quantix.db"
      }
    }
  }
}
```

Restart Claude Desktop. You will see the Quantix hammer/tool icon indicating all 10 tools are active!

---

## 🌐 Running Remotely Over Streamable HTTP

For remote deployment on a VPS, Docker container, or Kubernetes cluster:

1. In `.env`, set:
   ```ini
   MCP_TRANSPORT=streamable-http
   MCP_HOST=0.0.0.0
   MCP_PORT=8000
   MCP_API_KEY=your_secure_bearer_token_here
   ```
2. Start the server:
   ```bash
   uv run quantix
   ```
3. Test health probe:
   ```bash
   curl http://localhost:8000/health
   # Returns: {"status":"healthy","service":"quantix","version":"0.1.0",...}
   ```
4. Authenticate requests by including:
   `Authorization: Bearer your_secure_bearer_token_here`

---

## 🐳 Docker Deployment

A lightweight, non-root multi-stage Docker image is included:

```bash
# Build and start container with persistent SQLite volume
docker compose up -d --build

# Inspect logs
docker compose logs -f

# Check health
curl http://localhost:8000/health
```

---

## 🛠️ MCP Tools Directory

| Tool | Parameters | Purpose |
| :--- | :--- | :--- |
| `lookup_company` | `query: str` | Resolve ticker or company name to verified legal name, CIK, and ticker. |
| `list_filings` | `ticker, form_type="10-K", limit=5` | List recent official filings with accession numbers, dates, and direct links. |
| `get_financials` | `ticker, metric, periods=8, period_type="annual"` | Pull official XBRL financial time-series (revenue, net income, EPS, cash, debt, etc.). |
| `get_filing_section` | `ticker, form_type, section, accession_number=None` | Extract and clean Item 1 (Business), Item 1A (Risk Factors), Item 7 (MD&A), or Item 3 (Legal). |
| `diff_filings` | `ticker, section="risk_factors", form_type="10-K"` | Paragraph-level comparison between the two latest filings with AI synthesis. |
| `watch_ticker` | `ticker: str` | Add ticker to persistent tracking watchlist. |
| `unwatch_ticker` | `ticker: str` | Remove ticker from watchlist. |
| `list_watchlist` | None | List all currently monitored stocks. |
| `check_new_filings` | `ticker: Optional[str] = None` | Scan for un-alerted 8-K, 10-K, or 10-Q filings. |
| `company_brief` | `ticker: str` | One comprehensive, sourced briefing combining financials, diffs, and filings. |

### Example Prompts to Ask Your AI:
- *"What new risks did NVIDIA add in their most recent 10-K compared to the year before?"*
- *"Show me Microsoft's annual revenue and operating cash flow for the last 5 years with SEC accession links."*
- *"Add TSLA and AMZN to my watchlist and check if either has filed an 8-K this week."*
- *"Draft a 3-paragraph briefing on Apple's latest financial results and legal disclosures for my weekly newsletter."*

---

## 📬 Scheduled Telegram Alerts

Quantix includes an automated background job powered by `APScheduler`:
- Checks watched tickers for newly filed **Form 8-K** disclosures.
- Downloads the document, synthesizes a 3-to-5 sentence plain English summary using the LLM, and posts an alert with direct links to your Telegram channel.
- Accession numbers are tracked in SQLite to guarantee **zero duplicate alerts**.
- Configurable via `ALERT_SCHEDULE` (cron format, e.g. `0 8 * * 1-5` for 8:00 AM weekdays).

---

## ⚠️ Limitations & Notes

1. **SEC Rate Limiting:** The SEC strictly limits automated traffic to 10 requests per second. Quantix implements an internal token bucket rate limiter locked to **8 req/s**. Do not disable this limiter or your IP will receive temporary bans (HTTP 429).
2. **User-Agent Requirement:** SEC EDGAR policy requires all API consumers to supply a User-Agent in the form `AppName contact@example.com`. Quantix refuses to boot if `EDGAR_USER_AGENT` is missing or lacks an `@` sign.
3. **XBRL Concept Tag Variations:** Companies occasionally alter the specific US-GAAP tag used for concepts over time (e.g. changing between `Revenues` and `SalesRevenueNet`). Quantix handles this using dynamic fallback mapping and candidate period evaluation, but niche custom extension tags (`custom:SpecialRevenue`) may require standard GAAP reporting.
4. **Section Length & Truncation:** Complete 10-K risk factor sections can exceed 300,000 characters. To prevent context window overflow, Quantix applies a safe truncation budget with an explicit note pointing to the full official SEC archive URL.

---

## ⚖️ Legal Disclaimer

> **Informational only, not investment advice.**  
> Quantix is a research and educational data tool. Neither Quantix nor its output constitutes financial, legal, tax, or investment advice. Always consult official SEC filings directly at [sec.gov](https://www.sec.gov) and speak with a licensed financial advisor before making investment decisions.

