"""Headless CLI bot: runs the full matchday routine in one shot.

Unlike the wizard (server.py + Angular frontend), this mode executes every
decision directly against Mister without human review. Use it for cron-style
automation once you trust the engine's thresholds.
"""

from api import MisterAPI
from db_orm import get_db, get_value_drop_pct, init_db, upsert_player
from llm_checker import LLMNewsChecker
from strategy import StrategyEngine

# Only rivals' players above this value are worth auditing for a steal.
STEAL_MIN_VALUE = 3_000_000


def review_squad_health(checker: LLMNewsChecker, squad_players: list) -> None:
    """Batch medical review: flags hidden injuries Mister hasn't marked yet."""
    print("\n--- SQUAD MEDICAL REVIEW (AI) ---")
    candidates = [p for p in squad_players if p["status"] not in ("injured", "suspended")]
    verdicts = checker.check_players_status([p["name"] for p in candidates])

    for player in candidates:
        is_safe, reason = verdicts.get(player["name"], (True, ""))
        if not is_safe:
            print(f"[AI ALERT] Danger detected in {player['name']}! Reason: {reason}")
            # Mark as injured so the strategy engine forces an urgent sale.
            player["status"] = "injured"


def collect_received_offers(db, squad_players: list) -> list:
    """Builds the offers list for the engine from the enriched squad data."""
    offers = []
    for p in squad_players:
        offer = p.get("offer")
        if not offer:
            continue
        offers.append({
            "player_id": p["id"],
            "player_name": p["name"],
            "amount": offer["amount"],
            "id_bid": offer.get("id_bid", ""),
            "player_value": p.get("value", 0),
            "purchase_price": p.get("purchase_price"),
            "value_drop_pct": get_value_drop_pct(db, p["id"]),
        })
    return offers


def execute_sales(api: MisterAPI, engine: StrategyEngine,
                  squad_players: list, finances: dict,
                  market_offers: list | None = None) -> None:
    print("\n--- SALES & MANAGEMENT DECISIONS ---")
    decisions = engine.analyze_squad_and_offers(squad_players, finances, market_offers)
    if not decisions:
        print("> No recommended players to sell today.")
        return

    for decision in decisions:
        action, name = decision["action"], decision["player_name"]
        if action in ("SELL_URGENT", "SELL_BALANCE", "PUT_ON_MARKET"):
            print(f"[{action}] SELL {name} - {decision['reason']}")
            api.sell_player(decision["player_id"], decision.get("ask_price", 0))
        elif action == "ACCEPT_OFFER":
            print(f"[OFFER] ACCEPT {decision['amount']}€ for {name} - {decision['reason']}")
            api.lower_clause_to_minimum(decision["player_id"])
            api.accept_offer(decision["id_bid"], decision["amount"])


def execute_purchases(api: MisterAPI, engine: StrategyEngine,
                      checker: LLMNewsChecker, market_players: list,
                      finances: dict, squad_players: list) -> None:
    print("\n--- PURCHASE/BID DECISIONS ---")
    decisions = engine.analyze_market(market_players, finances, squad_players)
    if not decisions:
        print("> No players on the market meet the criteria today.")
        return

    # One batched AI call covers every candidate's injury/rotation news.
    verdicts = checker.check_players_status([d["player_name"] for d in decisions])

    for decision in decisions:
        name = decision["player_name"]
        is_safe, reason = verdicts.get(name, (True, ""))
        if not is_safe:
            print(f"[DISCARDED] {name} cancelled by AI: {reason}")
            continue
        print(f"[{decision['action']}] BID {decision['amount']}€ for {name} "
              f"- {decision['reason']}")
        api.place_bid(decision["player_id"], decision["amount"])


def execute_steals(api: MisterAPI, engine: StrategyEngine,
                   checker: LLMNewsChecker, squad_players: list,
                   finances: dict) -> None:
    """Hunts rival squads for unprotected, fairly-priced buyout clauses."""
    print("\n--- STEAL OPPORTUNITIES (CLAUSULAZOS) ---")
    my_team_id = str(api.get_lineup_metadata().get("team_id", ""))
    my_squad_ids = {p["id"] for p in squad_players}

    # 1. Collect financially-sound candidates (deterministic rules, no LLM).
    candidates = []
    for manager in api.get_community_users():
        if manager["id"] == my_team_id:
            continue

        print(f"> Analyzing squad of {manager['slug']}...")
        for rival_player in api.get_community_squad(manager["id"]):
            if rival_player["id"] in my_squad_ids:
                continue
            if rival_player["value"] < STEAL_MIN_VALUE:
                continue

            clause_data = (api.get_player_community_info(rival_player["id"])
                           .get("data", {}).get("clause", {}))
            shield = clause_data.get("shield", 0)
            clause_value = clause_data.get("value", 0)
            if shield != 0 or not (0 < clause_value <= finances["max_bid"]):
                continue

            is_good_deal, deal_reason = engine.evaluate_clausulazo(
                rival_player["value"], clause_value, finances["balance"]
            )
            if not is_good_deal:
                print(f"  -> [SKIPPED] {rival_player['name']}: {deal_reason}")
                continue

            print(f"  -> Candidate: {rival_player['name']} "
                  f"(Value: {rival_player['value']}€ | Clause: {clause_value}€)")
            candidates.append({
                "player": rival_player,
                "owner_id": manager["id"],
                "clause_value": clause_value,
            })

    if not candidates:
        print("> No viable steal candidates found.")
        return

    # 2. One batched medical audit for all candidates.
    verdicts = checker.check_players_status([c["player"]["name"] for c in candidates])

    # 3. Execute, tracking the remaining budget to avoid chained overspending.
    for candidate in candidates:
        player = candidate["player"]
        clause_value = candidate["clause_value"]
        if clause_value > finances["max_bid"]:
            print(f"  -> [SKIPPED] {player['name']}: budget exhausted by earlier steals.")
            continue

        is_safe, health_reason = verdicts.get(player["name"], (True, ""))
        if not is_safe:
            print(f"  -> [ABORTED] {player['name']} cancelled by medical AI: {health_reason}")
            continue

        print(f"  -> [CONFIRMED] Paying {clause_value}€ clause for {player['name']}!")
        api.steal_player(player["id"], candidate["owner_id"])
        finances["max_bid"] -= clause_value
        finances["balance"] -= clause_value


def set_best_lineup(api: MisterAPI, engine: StrategyEngine, squad_players: list) -> None:
    print("\n--- LINEUP OPTIMIZATION ---")
    meta = api.get_lineup_metadata()
    team_id, gwid = meta.get("team_id"), meta.get("gwid")
    if not (team_id and gwid):
        print("> [WARNING] Could not read team ID or matchday. Lineup not changed.")
        return

    lineup = engine.optimize_lineup(squad_players)
    if not lineup["formation"]:
        print("> [WARNING] Not enough players to form a valid 11.")
        return

    print(f"> Best formation: {lineup['formation']} "
          f"(estimated total score: {lineup['score']:.1f})")
    api.set_formation(team_id, lineup["formation"])
    for slot_num, player_id in lineup["slots"].items():
        api.substitute_player(team_id, gwid, slot_num, player_id)
    if lineup["captain_slot"]:
        api.set_captain(team_id, lineup["captain_slot"])
    print("> Lineup confirmed and sent to Mister!")


def main():
    print("=== Starting Wolf of Football Field (headless mode) ===")

    print("[1/5] Initializing local database...")
    init_db()
    db = next(get_db())

    print("[2/5] Connecting to Mister Fantasy...")
    api = MisterAPI()
    market_players = api.get_market()
    squad_players = api.get_user_squad()
    finances = api.get_user_finances()

    if not market_players or not squad_players:
        print("Critical error: could not fetch data from the API.")
        return

    # Authoritative per-player data: club membership, purchase price,
    # Mister's own injury report and received offers.
    api.get_squad_details(squad_players)

    print("[3/5] Synchronizing players with the database...")
    for player in market_players + squad_players:
        upsert_player(db, player)

    print("[4/5] Running strategy engine...")
    engine = StrategyEngine()
    checker = LLMNewsChecker()

    review_squad_health(checker, squad_players)
    market_offers = collect_received_offers(db, squad_players)
    execute_sales(api, engine, squad_players, finances, market_offers)
    execute_purchases(api, engine, checker, market_players, finances, squad_players)
    execute_steals(api, engine, checker, squad_players, finances)

    print("[5/5] Setting the best lineup...")
    set_best_lineup(api, engine, squad_players)

    print("\n=== Execution finished ===")


if __name__ == "__main__":
    main()
