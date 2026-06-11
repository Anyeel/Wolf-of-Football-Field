"""Deterministic decision engine for Mister Fantasy.

Everything in this module is rule-based and reproducible: scoring players,
picking the best lineup, deciding what to buy/sell and whether a buyout
clause ("clausulazo") is financially sound. The LLM (llm_checker.py) is only
consulted for qualitative judgement — injuries, rotations and the final
review — never for arithmetic.
"""

import datetime


class StrategyEngine:
    # --- Tunable thresholds -------------------------------------------------
    SAFE_BALANCE = 1_500_000          # Cash cushion to keep before a matchday
    MIN_ATTRACTIVE_SCORE = 30         # Score above which a player is a "core starter"

    # Bidding premiums over market value
    CORE_BID_PREMIUM = 1.08           # Pay up to +8% for core signings
    SPECULATION_PREMIUM = 1.01        # Pay only +1% when flipping for profit
    MIN_PRICE_THRESHOLD = 160_000     # Mister's minimum player price
    MIN_PRICE_BID = 160_001           # One euro above guarantees winning min-price auctions

    # Sale price multipliers
    RESALE_MULTIPLIER = 1.5           # Deterrent price for squad players on the market
    PROTECTION_MULTIPLIER = 2.0       # Deterrent price to shield stars from steals

    # Buyout-clause ("clausulazo") financial rules
    MAX_CLAUSE_PREMIUM = 1.5          # Never pay a clause above 150% of market value
    MAX_CLAUSE_BALANCE_SHARE = 0.7    # Never spend more than 70% of balance on one clause

    # Recent-form weights per streak label (last matches)
    STREAK_WEIGHTS = {
        'outstanding': 15,
        'good': 8,
        'fair': 2,
        'poor': -5,
        'failing': -10,
        'ns': 0,  # Did not play
    }

    ALLOWED_FORMATIONS = ['4-4-2', '4-5-1', '4-3-3', '3-4-3', '3-5-2', '5-4-1', '5-3-2']

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _calculate_attractiveness_score(self, player: dict) -> float:
        """Mixed score: season-long average plus recent streak momentum."""
        base_score = player.get('average_points', 0) * 5

        streak_score = 0
        for label in player.get('streak', [])[-5:]:  # Last 5 matches
            streak_score += self.STREAK_WEIGHTS.get(label, 0)

        return base_score + streak_score

    @staticmethod
    def _is_matchday_eve() -> bool:
        """La Liga matchdays start on Friday: avoid risky bids from then on."""
        return datetime.datetime.now().weekday() == 4

    # ------------------------------------------------------------------
    # Buyout clauses (deterministic — no LLM involved)
    # ------------------------------------------------------------------

    def evaluate_clausulazo(self, market_value: int, clause_value: int,
                            balance: int) -> tuple[bool, str]:
        """Rule-based check of whether paying a buyout clause is sound.

        This used to be delegated to the LLM, but it is pure arithmetic:
        a premium cap over market value and a balance-impact cap.
        """
        if clause_value <= 0 or market_value <= 0:
            return False, "Missing clause or market value data."

        premium = clause_value / market_value
        if premium > self.MAX_CLAUSE_PREMIUM:
            return False, (f"Clause is {premium:.0%} of market value "
                           f"(cap: {self.MAX_CLAUSE_PREMIUM:.0%}).")

        if clause_value > balance * self.MAX_CLAUSE_BALANCE_SHARE:
            return False, (f"Clause would consume over "
                           f"{self.MAX_CLAUSE_BALANCE_SHARE:.0%} of available balance.")

        return True, (f"Fair clause ({premium:.0%} of value) with healthy "
                      f"balance impact.")

    # ------------------------------------------------------------------
    # Market analysis (CLI bot)
    # ------------------------------------------------------------------

    def analyze_market(self, market_players: list, finances: dict) -> list:
        """Scans the free market for core signings, min-price steals and flips."""
        max_bid_capacity = finances.get('max_bid', 0)

        decisions = []
        spent_in_bids = 0

        # Best players first, so the budget goes to the strongest options.
        market_players = sorted(
            market_players, key=self._calculate_attractiveness_score, reverse=True
        )

        for player in market_players:
            if player.get('status') in ('injured', 'doubt'):
                continue

            player_value = player.get('value', 0)
            if player_value == 0:
                continue

            available_money = max_bid_capacity - spent_in_bids
            score = self._calculate_attractiveness_score(player)

            # 1. Core starter: worth paying a premium to actually win the auction.
            if score >= self.MIN_ATTRACTIVE_SCORE:
                suggested_bid = int(player_value * self.CORE_BID_PREMIUM)
                if suggested_bid <= available_money:
                    decisions.append({
                        'action': 'BID_CORE',
                        'player_id': player['id'],
                        'player_name': player['name'],
                        'amount': suggested_bid,
                        'reason': f"Core signing. Attractiveness score: {score:.1f}",
                    })
                    spent_in_bids += suggested_bid
                    continue

            # 2. Minimum-price player: guaranteed resale profit by outbidding by 1€.
            if player_value <= self.MIN_PRICE_THRESHOLD:
                if self.MIN_PRICE_BID <= available_money:
                    decisions.append({
                        'action': 'BID_MIN_PRICE',
                        'player_id': player['id'],
                        'player_name': player['name'],
                        'amount': self.MIN_PRICE_BID,
                        'reason': "Min-price signing (160k) for guaranteed resale profit.",
                    })
                    spent_in_bids += self.MIN_PRICE_BID
                    continue

            # 3. Speculation on rising values — never on matchday eve, when an
            #    unsold flip could leave the balance negative.
            if not self._is_matchday_eve() and player.get('trend') == 'up':
                suggested_bid = int(player_value * self.SPECULATION_PREMIUM)
                if suggested_bid <= available_money:
                    decisions.append({
                        'action': 'BID_SPECULATE',
                        'player_id': player['id'],
                        'player_name': player['name'],
                        'amount': suggested_bid,
                        'reason': "Speculation: value trending up (green arrow).",
                    })
                    spent_in_bids += suggested_bid

        return decisions

    # ------------------------------------------------------------------
    # Squad management (CLI bot)
    # ------------------------------------------------------------------

    def analyze_squad_and_offers(self, squad_players: list, finances: dict,
                                 market_offers: list | None = None) -> list:
        """Cleans up the squad and keeps the balance healthy before matchday."""
        current_balance = finances.get('balance', 0)

        # Never sell players the optimal lineup depends on.
        lineup_info = self.optimize_lineup(squad_players)
        protected_ids = set(lineup_info['slots'].values())

        decisions = []

        for player in squad_players:
            # Players without a real-life club score 0 every week: dump them.
            if not player.get('has_team', True):
                decisions.append({
                    'action': 'SELL_URGENT',
                    'player_id': player['id'],
                    'player_name': player['name'],
                    'reason': "No real-life team (left the league / free agent). Sell now.",
                })
                continue

            if player['id'] in protected_ids:
                continue

            if player.get('status') in ('injured', 'doubt') and player.get('trend') == 'down':
                decisions.append({
                    'action': 'SELL_URGENT',
                    'player_id': player['id'],
                    'player_name': player['name'],
                    'reason': "Injured and losing value (red arrow).",
                })
                continue

            # Bench players go on the market at a deterrent price: rivals can't
            # steal them cheap, and CPU offers keep coming in.
            if self._calculate_attractiveness_score(player) < self.MIN_ATTRACTIVE_SCORE:
                decisions.append({
                    'action': 'PUT_ON_MARKET',
                    'player_id': player['id'],
                    'player_name': player['name'],
                    'ask_price': int(player.get('value', 0) * self.RESALE_MULTIPLIER),
                    'reason': "Renew sale at deterrent price to block cheap steals.",
                })

        # Matchday cushion: if cash is short on matchday eve, sell the weakest
        # players first; starters are only touched once everyone else is gone.
        if self._is_matchday_eve() and current_balance < self.SAFE_BALANCE:
            deficit = self.SAFE_BALANCE - current_balance
            squad_sorted = sorted(squad_players, key=lambda p: (
                p['id'] in protected_ids,                 # Non-starters first
                self._calculate_attractiveness_score(p),  # Worst score first
            ))

            recovered = 0
            for player in squad_sorted:
                if recovered >= deficit:
                    break
                is_starter = player['id'] in protected_ids
                decisions.append({
                    'action': 'SELL_BALANCE',
                    'player_id': player['id'],
                    'player_name': player['name'],
                    'reason': (("URGENT: selling a starter " if is_starter else "Selling ")
                               + f"to restore the matchday cushion "
                               f"(missing {deficit - recovered}€)."),
                })
                recovered += player.get('value', 0)

        # Incoming offers: accept anything at or above market value.
        for offer in market_offers or []:
            if offer.get('from_rival_higher_ranked', False):
                continue  # Don't strengthen direct rivals above us
            if offer['amount'] >= offer['player_value']:
                decisions.append({
                    'action': 'ACCEPT_OFFER',
                    'id_bid': offer.get('id_bid', ''),
                    'player_id': offer['player_id'],
                    'player_name': offer['player_name'],
                    'amount': offer['amount'],
                    'reason': "Offer at or above market value (lower clause to minimum first).",
                })

        return decisions

    # ------------------------------------------------------------------
    # Lineup optimization
    # ------------------------------------------------------------------

    def optimize_lineup(self, squad_players: list) -> dict:
        """Finds the best legal formation, even with fewer than 11 fit players.

        Returns {'formation': '3-4-3', 'score': float,
                 'slots': {slot_number: player_id}, 'captain_slot': int|None}.
        """
        # Score every player once. Injured players are heavily penalized but
        # still usable: a fielded injured player scores 0, an empty slot -4.
        # Players who left the league are an even worse last resort.
        scores: dict[int, float] = {}
        by_pos: dict[str, list] = {'GK': [], 'DF': [], 'MF': [], 'FW': []}
        for p in squad_players:
            score = self._calculate_attractiveness_score(p)
            if p.get('status') == 'injured':
                score -= 1000
            if not p.get('has_team', True):
                score -= 2000
            scores[p['id']] = score

            pos = p.get('position', 'U')
            if pos in by_pos:
                by_pos[pos].append(p)

        for pos in by_pos:
            by_pos[pos].sort(key=lambda x: scores[x['id']], reverse=True)

        best = {'formation': None, 'score': float('-inf'), 'slots': {}, 'captain_slot': None}

        for formation in self.ALLOWED_FORMATIONS:
            req_df, req_mf, req_fw = (int(n) for n in formation.split('-'))

            selected = {
                'GK': by_pos['GK'][:1],
                'DF': by_pos['DF'][:req_df],
                'MF': by_pos['MF'][:req_mf],
                'FW': by_pos['FW'][:req_fw],
            }
            picked = [p for group in selected.values() for p in group]

            # Massive penalty per empty slot: prefer any complete 11.
            empty_slots = 11 - len(picked)
            total_score = sum(scores[p['id']] for p in picked) - empty_slots * 5000

            if total_score <= best['score']:
                continue

            # Map players onto Mister's rigid slot layout:
            # slot 1 = GK, then DF block, MF block, FW block.
            slots = {}
            slot_cursor = 1
            for pos_group in ('GK', 'DF', 'MF', 'FW'):
                block_size = {'GK': 1, 'DF': req_df, 'MF': req_mf, 'FW': req_fw}[pos_group]
                for i, p in enumerate(selected[pos_group]):
                    slots[slot_cursor + i] = p['id']
                slot_cursor += block_size

            captain_slot = max(slots, key=lambda s: scores[slots[s]], default=None)

            best = {
                'formation': formation,
                'score': total_score,
                'slots': slots,
                'captain_slot': captain_slot,
            }

        return best

    # ------------------------------------------------------------------
    # Wizard suggestions (frontend)
    # ------------------------------------------------------------------

    def get_market_suggestions(self, market_players: list,
                               rival_players: list | None = None) -> list:
        """Ranked list of signing targets: free agents plus possible steals."""
        suggestions = []

        for p in market_players:
            if p.get('status') in ('injured', 'doubt'):
                continue
            value = p.get('value', 0)
            if value == 0:
                continue

            bid = int(value * 1.05) if value > self.MIN_PRICE_THRESHOLD else self.MIN_PRICE_BID
            suggestions.append({
                'type': 'free_agent',
                'player_id': p['id'],
                'player_name': p['name'],
                'value': value,
                'score': self._calculate_attractiveness_score(p),
                'suggested_bid': bid,
                'reason': 'Agente libre',
            })

        for p in rival_players or []:
            if p.get('status') in ('injured', 'doubt'):
                continue
            value = p.get('value', 0)
            if value == 0:
                continue

            # Exact clauses aren't always parseable from rival pages, so only
            # very strong players are suggested, with an estimated clause.
            score = self._calculate_attractiveness_score(p)
            if score >= self.MIN_ATTRACTIVE_SCORE + 10:
                estimated_clause = int(value * self.MAX_CLAUSE_PREMIUM)
                suggestions.append({
                    'type': 'steal',
                    'player_id': p['id'],
                    'player_name': p['name'],
                    'value': value,
                    'clause': estimated_clause,
                    'score': score,
                    'suggested_bid': estimated_clause,
                    'owner_id': p.get('owner_id', ''),
                    'reason': 'Clausulazo a rival',
                })

        return sorted(suggestions, key=lambda s: s['score'], reverse=True)

    def get_protection_suggestions(self, squad_players: list) -> list:
        """Stars worth shielding: list them at 2x value so rivals can't steal them."""
        protections = []
        for p in squad_players:
            score = self._calculate_attractiveness_score(p)
            if score >= self.MIN_ATTRACTIVE_SCORE:
                value = p.get('value', 0)
                protections.append({
                    'player_id': p['id'],
                    'player_name': p['name'],
                    'score': score,
                    'value': value,
                    'suggested_price': int(value * self.PROTECTION_MULTIPLIER),
                    'reason': 'Jugador TOP — proteger con precio disuasorio',
                })
        return protections
