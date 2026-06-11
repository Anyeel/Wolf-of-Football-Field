"""FastAPI backend for the Wolf of Football Field wizard.

Exposes the Mister Fantasy data, the deterministic strategy engine and the
LLM layer to the Angular frontend. The expensive AI calls are batched
(/api/wizard/ai-precheck) or streamed (/api/wizard/ai-review) so the UI
never blocks on long inferences.
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api import MisterAPI
from db_orm import get_db, init_db, upsert_player
from llm_checker import LLMNewsChecker
from strategy import StrategyEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Wolf of Football Field API", lifespan=lifespan)

# The Angular dev server runs on another port, so CORS must be open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mister_api = MisterAPI()
engine = StrategyEngine()
checker = LLMNewsChecker()


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------

class StrategySettings(BaseModel):
    safe_balance: int
    min_attractive_score: int


class AIPrecheckRequest(BaseModel):
    players: List[str]


class WizardReviewRequest(BaseModel):
    cart_summary: str


class WizardExecuteRequest(BaseModel):
    bids: List[Dict[str, Any]]
    sales: List[Dict[str, Any]]
    protections: List[Dict[str, Any]]
    lineup: Dict[str, Any]


# ----------------------------------------------------------------------
# Status & data endpoints
# ----------------------------------------------------------------------

@app.get("/api/status")
def get_status():
    return {"status": "ok", "message": "FastAPI Backend is running"}


@app.get("/api/ai-status")
def get_ai_status():
    provider = checker.client.active_provider()
    if provider:
        return {"connected": True, "provider": provider.name}
    return {"connected": False, "provider": "AI Disconnected"}


@app.get("/api/market")
def get_market(db: Session = Depends(get_db)):
    players = mister_api.get_market()
    for p in players:
        upsert_player(db, p)  # Keep the local price history up to date
    return {"count": len(players), "players": players}


@app.get("/api/squad")
def get_squad(db: Session = Depends(get_db)):
    players = mister_api.get_user_squad()
    for p in players:
        upsert_player(db, p)
    return {"count": len(players), "players": players}


@app.get("/api/finances")
def get_finances():
    return mister_api.get_user_finances()


@app.get("/api/recommendations")
def get_recommendations():
    market = mister_api.get_market()
    squad = mister_api.get_user_squad()
    finances = mister_api.get_user_finances()
    return {
        "buy": engine.analyze_market(market, finances),
        "sell": engine.analyze_squad_and_offers(squad, finances),
        "finances": finances,
    }


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    return {
        "safe_balance": engine.SAFE_BALANCE,
        "min_attractive_score": engine.MIN_ATTRACTIVE_SCORE,
    }


@app.post("/api/settings")
def update_settings(settings: StrategySettings):
    engine.SAFE_BALANCE = settings.safe_balance
    engine.MIN_ATTRACTIVE_SCORE = settings.min_attractive_score
    return {"message": "Settings updated successfully", "settings": get_settings()}


# ----------------------------------------------------------------------
# Wizard flow
# ----------------------------------------------------------------------

@app.get("/api/wizard/init")
def wizard_init():
    """Step 1: download everything and compute the full matchday plan."""
    finances = mister_api.get_user_finances()
    market = mister_api.get_market()
    squad = mister_api.get_user_squad()

    rival_players = []
    for rival in mister_api.get_community_users():
        rival_players.extend(mister_api.get_community_squad(rival["id"]))

    market_suggestions = engine.get_market_suggestions(market, rival_players)
    lineup_info = engine.optimize_lineup(squad)
    protections = engine.get_protection_suggestions(squad)

    # Anything that is neither in the best 11 nor worth protecting is a sale.
    lineup_ids = set(lineup_info["slots"].values())
    protection_ids = {p["player_id"] for p in protections}
    sales = [
        {
            "player_id": p["id"],
            "player_name": p["name"],
            "value": p.get("value", 0),
            "suggested_price": int(p.get("value", 0) * engine.RESALE_MULTIPLIER),
        }
        for p in squad
        if p["id"] not in lineup_ids and p["id"] not in protection_ids
    ]

    return {
        "finances": finances,
        "market_suggestions": market_suggestions,
        "lineup": lineup_info,
        "squad": squad,
        "sales": sales,
        "protections": protections,
        "rival_players": rival_players,
    }


@app.post("/api/wizard/ai-precheck")
def wizard_ai_precheck(req: AIPrecheckRequest):
    """Batched injury/rotation check: one LLM call for the whole list."""
    verdicts = checker.check_players_status(req.players)
    return {
        "verdicts": {
            name: {"safe": safe, "reason": reason}
            for name, (safe, reason) in verdicts.items()
        }
    }


@app.post("/api/wizard/ai-review")
def wizard_ai_review(req: WizardReviewRequest):
    """Streaming SSE endpoint: pipes LLM tokens to the frontend in real time."""
    return StreamingResponse(
        checker.evaluate_cart_stream(req.cart_summary),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/wizard/execute")
def wizard_execute(req: WizardExecuteRequest):
    """Final step: pushes the confirmed plan to the real Mister API."""
    for bid in req.bids:
        if bid.get("type") == "steal":
            mister_api.steal_player(bid["player_id"], bid["owner_id"])
        else:
            mister_api.place_bid(bid["player_id"], bid["suggested_bid"])

    for sale in req.sales:
        if sale.get("action") == "accept":
            mister_api.accept_offer(sale["id_bid"], sale["suggested_price"])
        elif sale.get("action") == "renew":
            mister_api.renew_player(sale["id_market"])
        else:
            mister_api.sell_player(sale["player_id"], sale["suggested_price"])

    for protection in req.protections:
        mister_api.sell_player(protection["player_id"], protection["suggested_price"])

    meta = mister_api.get_lineup_metadata()
    team_id, gwid = meta.get("team_id"), meta.get("gwid")
    if team_id and gwid and req.lineup.get("formation"):
        mister_api.set_formation(team_id, req.lineup["formation"])
        for slot, player_id in req.lineup.get("slots", {}).items():
            mister_api.substitute_player(team_id, gwid, slot, player_id)
        if req.lineup.get("captain_slot"):
            mister_api.set_captain(team_id, req.lineup["captain_slot"])

    return {"success": True, "message": "Operaciones ejecutadas con éxito en Mister."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
