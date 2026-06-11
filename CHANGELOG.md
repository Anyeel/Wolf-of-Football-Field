# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-06-11
### Added
- **LLM Provider Abstraction** (`llm_client.py`): a single client routes requests to local Ollama first and falls back to **Google Gemini** (plain REST, no SDK) automatically — including streaming. The fallback that was previously only advertised now actually works.
- **Structured AI Output**: injury checks now use schema-constrained decoding (Ollama `format` / Gemini `responseSchema`), so the model's verdict is always parseable JSON instead of fragile `STATUS:`/`REASON:` string splitting.
- **Batched Injury Pre-check** (`POST /api/wizard/ai-precheck`): one LLM call covers the whole market instead of one search + one inference per player. Wizard init went from minutes to seconds on large markets.
- **Typed Angular frontend**: shared domain models (`models.ts`), typed `WizardService`, and the wizard split into separate `.ts`/`.html`/`.css` files with a redesigned UI (stepper with progress, market cards, striped pitch with penalty areas, stats summary, success screen).
- **New tests**: deterministic clause rules, batched checker parsing, fail-safe finances (16 backend tests + 5 frontend specs).
- **MIT LICENSE** file (the README badge finally tells the truth).

### Changed
- **Buyout-clause evaluation is now deterministic** (`StrategyEngine.evaluate_clausulazo`): premium and balance-impact caps are arithmetic, not something to ask a 9B model about. The LLM is reserved for qualitative judgement (news analysis, final review).
- **Fail-safe finances**: when the real balance cannot be read, the API now reports 0€ (no bids) instead of a fictional 15M€ fallback that allowed blind spending.
- `api.py` reuses a single `requests.Session`, `place_bid` reuses `get_player_community_info`, and `main.py` was modularized into per-phase functions (no more hardcoded account IDs).
- Frontend SSE reader now buffers chunks correctly (a `data:` line split across network chunks no longer gets dropped).

### Removed
- Legacy `db.py` (raw-SQLite duplicate of `db_orm.py`).
- Per-player `GET /api/evaluate-ai` endpoint, replaced by the batched pre-check.

### Fixed
- Matchday-cushion logic could mark starters for sale even when selling cheaper bench players was enough.

## [1.2.0] - 2026-06-10
### Added
- **Wizard Flow Frontend**: Completely redesigned the Angular app to follow a sequential, step-by-step Wizard UI for daily management instead of the scattered dashboard.
- **Local Shopping Cart**: Implemented real-time balance projections in the frontend. It automatically unchecks the worst suggested bids if projected balance drops below zero, preventing bankruptcy.
- **Final AI Evaluation**: The whole "shopping cart" (bids, lineup, and sales) is now sent to the LLM for a final review before actually hitting the Mister API.
- **Player Protection Logic**: The strategy engine now identifies top-performing players with low market value/clauses and automatically suggests putting them on the market at 2x their value to protect them from steals.
- **FutbolFantasy Scraper**: Upgraded the AI news verification system (`llm_checker.py`) to specifically search and scrape news directly from `futbolfantasy.com` for maximum accuracy regarding injuries and rotations.
- **Visual Lineup Editor**: Added a football pitch interface using CSS/SVG to visually display the calculated starting 11.
- **Streaming AI Evaluation (SSE)**: The AI review now uses Server-Sent Events to stream Ollama's response token by token. No timeout limits — scales to any league size.
- **`.gitignore`**: Added a comprehensive root `.gitignore` covering Python venvs, `node_modules`, `.env`, SQLite databases, IDE files, and debug artifacts.

### Removed
- Removed the old Tinder-style `DashboardComponent` and `SidebarComponent` in favor of a full-screen guided experience.
- Cleaned up debug HTML files (`market.html`, `team.html`, etc.) from backend.

### Changed
- **Rebranded** the project from "Mister Fantasy AI" to **Wolf of Football Field** 🐺.

## [1.1.0] - 2026-06-09
### Added
- Complete architecture migration to a **Fullstack** application.
- **FastAPI Backend:** Replaced standard CLI execution with a robust REST API (`server.py`).
- **SQLAlchemy ORM:** Migrated raw SQLite queries to a structured ORM (`db_orm.py`).
- **Angular Frontend:** Replaced temporary React implementation with an Enterprise-grade Angular frontend (Lazy Loaded UI, Glassmorphism).
- **Local AI Integration (Ollama)**: Integrated `qwen3.5:9b` via local Ollama for real-time sports news analysis and injury detection without API costs.
- **Lazy Loading Architecture**: Redesigned the AI evaluation pipeline to evaluate players asynchronously (player-by-player) in the frontend to prevent backend timeouts and improve UX.
- **Execution Endpoint**: Added `POST /api/execute` to allow the frontend to execute bids and sales directly on Mister Fantasy.
- **Starting 11 Protection**: The strategy engine now calculates the ideal lineup and strictly prevents selling essential players (like the only Goalkeeper) to avoid matchday penalties.
- **Free Agent Auto-Sale**: Added logic to instantly detect and sell players who do not belong to any real-life team (Free Agents/Left the league).
- **News Recency Filter**: DuckDuckGo search now exclusively queries news from the last 7 days (`timelimit='w'`) to prevent AI hallucinations based on old injuries.

### Changed
- Translated all Python files, comments, and docstrings from Spanish to English for a Portfolio-ready codebase.
- Improved backend error handling so AI failures do not crash the entire recommendation engine (Fallback support).
- Changed DDGS import logic to adapt to the official package rename from `duckduckgo_search` to `ddgs`.

## [1.0.0] - Initial Release
### Added
- Core Python CLI bot.
- Market analysis engine (`strategy.py`) capable of bidding, speculating, and stealing players ("clausulazos").
- Web scraping and API connection logic (`api.py`).
- Local SQLite database tracking player history (`db.py`).
- First integration of AI for medical/status checks (`llm_checker.py`).
