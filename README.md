<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:1B5E20,50:2E7D32,100:66BB6A&height=220&section=header&text=Wolf%20of%20Football%20Field&fontSize=48&fontColor=fff&fontAlignY=30&desc=The%20AI%20That%20Plays%20Fantasy%20Football%20Better%20Than%20You&descAlignY=52&descSize=16" width="100%" />
</p>

<p align="center">
  <img src="docs/wolf_hero.jpg" width="500" style="border-radius: 12px;" />
</p>

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&size=18&duration=3500&pause=800&color=66BB6A&center=true&vCenter=true&width=700&lines=I'm+not+leaving.+I'm+NOT+LEAVING!;The+market+is+my+playground;Sell+the+dip%2C+buy+the+clausulazo;Powered+by+Ollama+%2B+FastAPI+%2B+Angular;Built+different.+Built+to+win." />
</p>

<p align="center">
  <a href="#-features"><img src="https://img.shields.io/badge/Features-1B5E20?style=for-the-badge&logo=sparkles&logoColor=white" /></a>
  <a href="#%EF%B8%8F-architecture"><img src="https://img.shields.io/badge/Architecture-2E7D32?style=for-the-badge&logo=grid&logoColor=white" /></a>
  <a href="#-getting-started"><img src="https://img.shields.io/badge/Getting%20Started-388E3C?style=for-the-badge&logo=rocket&logoColor=white" /></a>
  <a href="#-how-it-works"><img src="https://img.shields.io/badge/How%20It%20Works-43A047?style=for-the-badge&logo=brain&logoColor=white" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/angular-18-DD0031?style=flat-square&logo=angular&logoColor=white" />
  <img src="https://img.shields.io/badge/fastapi-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/ollama-local_LLM-000000?style=flat-square&logo=ollama&logoColor=white" />
  <img src="https://img.shields.io/badge/gemini-cloud_fallback-4285F4?style=flat-square&logo=googlegemini&logoColor=white" />
  <img src="https://img.shields.io/badge/license-MIT-66BB6A?style=flat-square" />
</p>

---

## 🎯 What is this?

**Wolf of Football Field** is an AI copilot for [Mister Fantasy](https://mister.mundodeportivo.com/) — the most popular Fantasy Football platform in Spain. It connects to the official API, scrapes market data, analyzes player performance, and uses an LLM (local Ollama, with automatic Gemini cloud fallback) to make informed decisions about signings, sales, lineup optimization, and rival analysis.

> *"The only thing standing between you and your goal is the bullshit story you keep telling yourself as to why you can't achieve it."* — Except now, AI tells the story for you.

Instead of spending hours every matchday clicking through menus, you get a **5-step guided Wizard** that prepares your entire strategy in one go, lets you tweak it, and executes everything with a single click.

### Design philosophy: the LLM never does math

Every financial decision (bid premiums, buyout-clause caps, balance cushions) is **deterministic and rule-based** in `strategy.py`. The LLM is reserved for what it's actually good at: reading injury news, judging rotations, and giving a final tactical review of your plan. No 9B model is asked whether 4M > 70% of 5M.

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🧙 Guided Wizard Flow
A 5-step process that walks you through your entire matchday strategy:
1. **Init** — Downloads market, squad, and rival data
2. **Market** — Browse and select signings with live balance tracking
3. **Lineup** — Visual football pitch with your best XI and captain
4. **Sales & Protection** — Auto-sell deadweight, shield star players
5. **AI Review & Execute** — Final LLM evaluation before committing

</td>
<td width="50%">

### 🤖 Dual-Provider AI Layer
A provider abstraction (`llm_client.py`) talks to **local Ollama** first and falls back to **Google Gemini** (plain REST, no SDK) when Ollama is offline — for both single-shot and streaming generation. If neither is available, a keyword analyzer keeps the bot functional.

### 📋 Structured AI Output
Injury verdicts use **schema-constrained decoding** (Ollama `format` / Gemini `responseSchema`): the model can only answer with valid JSON. No regex archaeology on free-form text.

</td>
</tr>
<tr>
<td width="50%">

### 🩺 Batched Injury Pre-check
One LLM call audits the **entire market shortlist** at once: news snippets for every candidate are gathered from [futbolfantasy.com](https://futbolfantasy.com) and judged in a single inference. Wizard init takes seconds, not minutes.

### 🛡️ Player Protection
Automatically detects undervalued star players in your squad and suggests putting them on the market at 2x value to prevent rival steals (*clausulazos*).

</td>
<td width="50%">

### 📡 Streaming AI Review (SSE)
The final review streams Ollama/Gemini tokens to the browser via **Server-Sent Events** — you watch the AI "think" in real time. No timeouts, works with any league size.

### 💰 Smart Balance Management
The frontend cart **recalculates your projected balance in real time**. If you go negative, it automatically drops the lowest-scored bids until you're solvent again. *Sell high, buy low.*

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    FRONTEND (Angular 18)                  │
│                                                          │
│   Wizard UI ──► Shopping Cart ──► SSE Stream Reader      │
│       │              │                    │               │
│       ▼              ▼                    ▼               │
│   [Init] ──► [Market] ──► [Lineup] ──► [Sales] ──► [AI]  │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼─────────────────────────────────┐
│                   BACKEND (FastAPI)                       │
│                                                          │
│   server.py ──── strategy.py ──── llm_checker.py         │
│   (endpoints)    (rule engine,    (news scraping,        │
│                   all the math)    batched verdicts)     │
│                                        │                  │
│   api.py                          llm_client.py           │
│   (Mister scraper/client)         (provider routing)      │
│       │                            │            │         │
│       ▼                            ▼            ▼         │
│   [Mister Fantasy API]      [Ollama local] [Gemini REST]  │
└──────────────────────────────────────────────────────────┘
```

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Angular 18, TypeScript, Vanilla CSS | Wizard UI, real-time balance, SSE stream consumer |
| **Backend** | Python 3.10+, FastAPI, SQLAlchemy | REST API, deterministic strategy engine, streaming proxy |
| **AI/LLM** | Ollama (local) + Gemini (fallback) | Injury analysis, rotation checks, final cart review |
| **Data** | SQLite, BeautifulSoup | Player history tracking, web scraping |
| **News** | DuckDuckGo Search | futbolfantasy.com filtered news scraping |

---

## 🚀 Getting Started

### Prerequisites

| Tool | Version | Required |
|------|---------|----------|
| Python | 3.10+ | ✅ |
| Node.js | 18+ | ✅ |
| Ollama | Latest | ⭐ Recommended (or a Gemini API key) |

### 1. Clone & Setup Backend

```bash
git clone https://github.com/your-username/wolf-of-football-field.git
cd wolf-of-football-field/backend

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env with your Mister Fantasy tokens (see below)
```

### 2. Get Your Mister Fantasy Token

1. Log into [Mister Fantasy](https://mister.mundodeportivo.com/) in your browser
2. Open DevTools (`F12`) → **Network** tab
3. Click on any request and find the `X-Auth` header → That's your `MISTER_AUTH_TOKEN`
4. Copy the `Cookie` header into `MISTER_COOKIE`; your league ID is visible in the URL

### 3. Setup an AI Provider

```bash
# Option A (recommended): local Ollama — free and private
# Install from https://ollama.com, then:
ollama pull qwen3.5:9b

# Option B: Gemini cloud fallback — set GEMINI_API_KEY in .env
# (used automatically whenever Ollama is not running)
```

### 4. Start the Backend

```bash
cd backend
python server.py
# API running at http://localhost:8000
```

### 5. Start the Frontend

```bash
cd frontend
npm install
npm start
# Open http://localhost:4200
```

---

## 🔄 How It Works

```mermaid
sequenceDiagram
    participant U as 👤 User
    participant F as 🖥️ Frontend
    participant B as ⚙️ Backend
    participant M as ⚽ Mister API
    participant AI as 🤖 LLM (Ollama/Gemini)

    U->>F: Click "Iniciar análisis"
    F->>B: GET /api/wizard/init
    B->>M: Fetch market, squad, rivals
    M-->>B: Raw player data
    B->>B: Run deterministic strategy engine
    B-->>F: Suggestions, lineup, sales, protections

    F->>B: POST /api/wizard/ai-precheck (top candidates)
    B->>AI: ONE batched prompt + JSON schema
    AI-->>B: Structured verdict per player
    B-->>F: Injured/rotating players auto-discarded

    U->>F: Adjust bids, review lineup
    F->>F: Recalculate balance in real-time

    U->>F: Click "Evaluar jugada con IA"
    F->>B: POST /api/wizard/ai-review (SSE)
    B->>AI: Stream prompt with full context
    AI-->>F: Token by token, in real time

    U->>F: Click "CONFIRMAR Y EJECUTAR"
    F->>B: POST /api/wizard/execute
    B->>M: Place bids, set lineup & captain, sell players
    M-->>B: Confirmation
    B-->>F: Success ✅
```

---

## 🧪 Testing

```bash
# Backend (16 tests: strategy rules, HTML parsing, AI layer)
cd backend
pytest

# Frontend (component & service specs)
cd frontend
npx ng test --watch=false --browsers=ChromeHeadless
```

---

## 📁 Project Structure

```
wolf-of-football-field/
├── backend/
│   ├── server.py          # FastAPI application & endpoints
│   ├── api.py             # Mister Fantasy web scraper & API client
│   ├── strategy.py        # Deterministic decision engine (market, lineup, clauses)
│   ├── llm_client.py      # Provider abstraction: Ollama + Gemini fallback
│   ├── llm_checker.py     # News scraping + batched AI verdicts + SSE review
│   ├── db_orm.py          # SQLAlchemy ORM models
│   ├── main.py            # CLI mode (headless bot)
│   ├── tests/             # pytest suite
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/app/
│       ├── models.ts            # Shared domain types
│       ├── services/            # Typed HTTP service
│       └── pages/wizard/        # Wizard UI (ts / html / css)
├── docs/
│   └── wolf_hero.jpg      # Project hero image
├── LICENSE
├── CHANGELOG.md
└── README.md
```

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to open a PR or issue.

## 📄 License

Released under the [MIT License](LICENSE).

---

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:1B5E20,50:2E7D32,100:66BB6A&height=120&section=footer" width="100%" />
</p>

<p align="center">
  <sub>Built with 🐺 energy and a lot of ⚽ by <a href="https://github.com/your-username">your-username</a></sub>
</p>
