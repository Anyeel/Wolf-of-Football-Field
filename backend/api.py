"""HTTP client for the (undocumented) Mister Fantasy web API.

Mister has no public API: this client replays the same AJAX calls the web
app makes, authenticated with the X-Auth token and session cookie captured
from the browser (see .env.example). Player lists are returned as partial
HTML fragments, which are parsed with BeautifulSoup.
"""

import os
import re

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Mister sometimes hides the matchday countdown; bidding above balance is
# only allowed when the matchday is comfortably far away.
BID_MARGIN_NORMAL = 1.15   # Up to +15% over balance (pending sales cover it)
BID_MARGIN_STRICT = 1.0    # Matchday imminent: never risk a negative balance

POSITION_MAP = {'1': 'GK', '2': 'DF', '3': 'MF', '4': 'FW'}


class MisterAPI:
    def __init__(self):
        self.base_url = "https://mister.mundodeportivo.com"
        self.auth_token = os.getenv("MISTER_AUTH_TOKEN")
        self.league_id = os.getenv("MISTER_LEAGUE_ID")
        self.cookie = os.getenv("MISTER_COOKIE")

        if not self.auth_token or not self.cookie:
            raise ValueError(
                "MISTER_AUTH_TOKEN and MISTER_COOKIE are required in the .env file"
            )

        self.headers = {
            "X-Auth": self.auth_token,
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/148.0.0.0 Safari/537.36"),
            "Accept": "*/*",
            "x-league": self.league_id or "",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": self.cookie,
            "partial-request": "true",
            "origin": self.base_url,
            "referer": f"{self.base_url}/team",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    def _get_html_raw(self, endpoint: str) -> str:
        """Fetches a page as raw partial HTML.

        Mister returns the partial fragment only for a POST with an empty
        body (mimicking the web app's navigation requests).
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            response = self.session.post(url, data="")
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"[API] HTML request to {endpoint} failed: {e}")
            return ""

    def _get_players(self, endpoint: str) -> list:
        """Fetches a page and parses every player row found in it."""
        print(f"[API] Downloading data from /{endpoint}...")
        html = self._get_html_raw(endpoint)
        if not html:
            return []
        players = self._parse_players_html(html)
        if not players:
            print(f"[DEBUG] No players found at /{endpoint}. First 500 chars of response:")
            print(html[:500])
        return players

    def _post_form(self, endpoint: str, data_raw: str) -> bool:
        """POSTs a form-encoded action and reports success."""
        url = f"{self.base_url}/{endpoint}"
        print(f"[API] Executing action at /{endpoint}...")
        headers = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            response = self.session.post(url, headers=headers, data=data_raw)
            response.raise_for_status()
            return True
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                # Mister answers 400 for business rejections (player already
                # lined up, bid limit exceeded, insufficient balance...).
                print("      -> [SKIPPED] Mister rejected the action.")
            else:
                print(f"[ERROR] Action failed on Mister: {e}")
            return False
        except requests.RequestException as e:
            print(f"[ERROR] Connection to Mister failed: {e}")
            return False

    @staticmethod
    def _format_price(amount: int) -> str:
        """Mister expects prices with dots as thousands separators (1.234.567)."""
        return f"{amount:,}".replace(",", ".")

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------

    def get_market(self) -> list:
        """Players currently for sale on the market."""
        return self._get_players("market")

    def get_user_squad(self) -> list:
        """The user's current squad."""
        return self._get_players("team")

    def get_user_finances(self) -> dict:
        """Available balance, with a max-bid margin based on matchday proximity.

        Returns {'balance': int, 'max_bid': int}. If the balance cannot be
        read, both are 0 so the engine never bids with made-up money.
        """
        safe_margin = BID_MARGIN_NORMAL

        # 1. How long until the matchday starts?
        team_html = self._get_html_raw("team")
        match = re.search(
            r'gameweek__status[^>]*>\s*(?:Empieza.*?)\s*(\d+)\s*(d|hora|minuto)',
            team_html, re.IGNORECASE | re.DOTALL,
        )
        if match:
            qty, unit = int(match.group(1)), match.group(2).lower()
            if unit.startswith(('hora', 'minuto')) or (unit.startswith('d') and qty <= 1):
                safe_margin = BID_MARGIN_STRICT
                print(f"\n[MATCHDAY ALERT] Matchday starts in {qty} {unit}. "
                      "Bidding above balance is disabled (negative-balance risk).")
            else:
                print(f"\n[INFO] {qty} days until matchday. "
                      f"Bid margin: +{(safe_margin - 1) * 100:.0f}% over balance.")

        # 2. Actual balance.
        headers = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            resp = self.session.post(f"{self.base_url}/ajax/sw/balance",
                                     headers=headers, data="post=balance")
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "ok":
                balance = data["data"]["balance"]
                return {"balance": balance, "max_bid": int(balance * safe_margin)}
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[API] Error getting balance: {e}")

        # Fail-safe: with no real data, report zero so nothing gets bought.
        print("[API] WARNING: balance unavailable — reporting 0€ to prevent blind bids.")
        return {"balance": 0, "max_bid": 0}

    def get_player_community_info(self, player_id) -> dict:
        """Detailed market/bid/clause info for a single player."""
        headers = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            resp = self.session.post(f"{self.base_url}/ajax/player-community-info",
                                     headers=headers, data=f"id_player={player_id}")
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"[API] Warning: could not get community info for player {player_id}: {e}")
        return {}

    def get_squad_details(self, squad_players: list) -> list:
        """Enriches squad players in place with authoritative JSON data.

        The HTML player rows are unreliable for club membership (every row
        carries a team-logo img), so this uses player-community-info, where
        `team` is null for players who left the league. It also exposes the
        purchase price, current listing, Mister's own injury report and any
        received offer — data the strategy engine needs for sale decisions.
        """
        for p in squad_players:
            data = self.get_player_community_info(p["id"]).get("data", {})
            if not data:
                continue

            # Authoritative club membership: null team = left the league.
            p["has_team"] = bool(data.get("team"))

            transfer = data.get("transfer") or {}
            p["purchase_price"] = transfer.get("price")

            market = data.get("market") or {}
            p["on_market"] = market.get("id") is not None
            p["id_market"] = market.get("id")
            p["ask_price"] = market.get("price")

            # Mister's own injury report beats any news scraping.
            if data.get("injury"):
                p["status"] = "injured"

            # For an owned player, the bid block carries the received offer
            # (amount + days until it expires), if there is one.
            bid = data.get("bid") or {}
            if bid.get("isActive") == 1 and bid.get("amount"):
                p["offer"] = {
                    "amount": bid["amount"],
                    "id_bid": bid.get("id", ""),
                    "days": bid.get("days"),
                }
        return squad_players

    def get_community_users(self) -> list:
        """IDs and slugs of the other managers in the league."""
        html = self._get_html_raw("standings")
        return [
            {"id": m.group(1), "slug": m.group(2)}
            for m in re.finditer(r'href="users/(\d+)/([^"]+)"', html)
        ]

    def get_community_squad(self, user_id) -> list:
        """The squad of a rival manager."""
        return self._get_players(f"users/{user_id}")

    def get_lineup_metadata(self) -> dict:
        """Extracts team_id and gwid (current matchday) from the team page."""
        html = self._get_html_raw("team")

        gwid_match = (re.search(r'data-gwid=["\'](\d+)["\']', html)
                      or re.search(r'gwid["\']?\s*[:=]\s*["\']?(\d+)', html))
        team_id_match = (re.search(r'data-id_owner=["\'](\d+)["\']', html)
                         or re.search(r'id_team["\']?\s*[:=]\s*["\']?(\d+)', html))

        return {
            "team_id": team_id_match.group(1) if team_id_match else None,
            "gwid": gwid_match.group(1) if gwid_match else None,
        }

    # ------------------------------------------------------------------
    # Write endpoints (market actions)
    # ------------------------------------------------------------------

    def place_bid(self, player_id, amount: int) -> bool:
        """Places a bid for a player on the market."""
        info = self.get_player_community_info(player_id).get("data", {})

        if info.get("bid", {}).get("isActive", 0) == 1:
            print("      -> [SKIPPED] You already have an active bid for this player.")
            return False

        id_market = info.get("market", {}).get("id", "")
        if not id_market:
            print("      -> [SKIPPED] Player is no longer available on the market.")
            return False

        data = (f"offeree_id=&id_market={id_market}&id_player={player_id}"
                f"&action=bid&bid={self._format_price(amount)}&bid_range={amount}")
        return self._post_form("ajax/bid", data)

    def sell_player(self, player_id, amount: int) -> bool:
        """Puts a player on the transfer list at the given price."""
        data = (f"id_player={player_id}&action=sale"
                f"&price={self._format_price(amount)}&price={amount}")
        if self.league_id:
            data += f"&id_competition={self.league_id}"
        return self._post_form("ajax/sale", data)

    def steal_player(self, player_id, target_user_id) -> bool:
        """Pays a rival player's buyout clause ('clausulazo')."""
        print(f"[API] Paying buyout clause for player {player_id} "
              f"(owner: manager {target_user_id})...")
        data = f"id_player={player_id}&id_uc={target_user_id}&id_giphy="
        return self._post_form("ajax/clause-pay", data)

    def accept_offer(self, id_bid, amount: int) -> bool:
        """Accepts an incoming market offer for one of our players."""
        print(f"[API] Accepting offer {id_bid} for {amount}€...")
        data = f"id_bid={id_bid}&type=accept&amount={amount}"
        return self._post_form("ajax/offer", data)

    def renew_player(self, id_market) -> bool:
        """Re-lists a player on the market (cancels stale offers)."""
        print(f"[API] Renewing market listing {id_market}...")
        return self._post_form("ajax/resale", f"id_market={id_market}")

    def lower_clause_to_minimum(self, player_id) -> bool:
        """Drops the release clause to 1€ (done right before accepting an offer)."""
        return self._post_form("ajax/clause-set", f"id_player={player_id}&shield=0&clause=1")

    # ------------------------------------------------------------------
    # Write endpoints (lineup)
    # ------------------------------------------------------------------

    def set_formation(self, team_id, formation_str: str) -> bool:
        """Changes the team formation (e.g. '3-5-2')."""
        data = f"id={team_id}&formation={formation_str}"
        if self.league_id:
            data += f"&id_competition={self.league_id}"
        return self._post_form("ajax/formation", data)

    def substitute_player(self, team_id, gwid, slot, player_id) -> bool:
        """Places a player into a starting-lineup slot."""
        data = (f"isstarted=false&gwid={gwid}&id={team_id}"
                f"&sku=change_player&slot={slot}&id_player={player_id}")
        return self._post_form("ajax/sub-do", data)

    def set_captain(self, team_id, slot_index: int) -> bool:
        """Sets the captain by lineup slot (the forge API expects JSON)."""
        url = f"{self.base_url}/forge/bemanager/managers/{team_id}/lineup/captain"
        print(f"[API] Setting captain for team {team_id} at slot {slot_index}...")
        try:
            response = self.session.post(
                url,
                headers={"content-type": "application/json"},
                json={"slot_index": slot_index},
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"[ERROR] Failed to set captain: {e}")
            return False

    # ------------------------------------------------------------------
    # HTML parsing
    # ------------------------------------------------------------------

    def _parse_players_html(self, html_content: str) -> list:
        """Extracts the player list from a Mister partial-HTML fragment."""
        soup = BeautifulSoup(html_content, "html.parser")
        players = []
        for row in soup.select(".player-row"):
            avatar_div = row.select_one(".player-avatar")
            if not avatar_div or "data-id_player" not in avatar_div.attrs:
                continue
            player_id = int(avatar_div["data-id_player"])

            name_div = row.select_one(".name")
            if not name_div:
                continue
            name = name_div.text.strip()

            points_div = row.select_one(".points")
            points = int(points_div.text.strip()) \
                if points_div and points_div.text.strip().isdigit() else 0

            value = 0
            price_div = row.select_one(".underName")
            if price_div:
                digits = "".join(c for c in price_div.text if c.isdigit())
                value = int(digits) if digits else 0

            position = "U"
            pos_div = row.select_one(".player-position")
            if pos_div and "data-position" in pos_div.attrs:
                position = POSITION_MAP.get(pos_div["data-position"], "U")

            trend = "flat"
            arrow_span = row.select_one(".value-arrow")
            if arrow_span:
                arrow_classes = arrow_span.get("class", [])
                if "green" in arrow_classes:
                    trend = "up"
                elif "red" in arrow_classes:
                    trend = "down"

            streak = []
            streak_div = row.select_one(".streak")
            if streak_div:
                for span in streak_div.find_all("span"):
                    classes = span.get("class", [])
                    if classes:
                        streak.append(classes[0].replace("bg--", ""))

            status = "ok"
            if row.select_one(".st-injury") or row.select_one('use[href*="#injury"]'):
                status = "injured"
            elif row.select_one('use[href*="#doubt"]'):
                status = "doubt"

            # Free agents / players who left the league lack a team shield, or
            # show a cross icon. They score nothing and must be sold.
            has_team = bool(
                row.select_one("a.team-logo")
                or row.select_one(".shield")
                or row.select_one("img.team-logo")
            )
            if row.select_one('use[href*="#cross"]') or row.select_one('use[href*="#quit"]'):
                has_team = False

            players.append({
                "id": player_id,
                "name": name,
                "team": "Unknown",
                "position": position,
                "points": points,
                # Season average; Mister doesn't expose games played in this view.
                "average_points": points / 38.0 if points > 0 else 0.0,
                "value": value,
                "trend": trend,
                "streak": streak,
                "status": status,
                "has_team": has_team,
            })
        return players


if __name__ == "__main__":
    api = MisterAPI()
    print("Market:", api.get_market())
