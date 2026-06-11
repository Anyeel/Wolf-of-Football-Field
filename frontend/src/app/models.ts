/**
 * Shared domain models mirroring the FastAPI backend responses.
 */

export type Position = 'GK' | 'DF' | 'MF' | 'FW' | 'U';
export type Trend = 'up' | 'down' | 'flat';
export type PlayerStatus = 'ok' | 'injured' | 'doubt';

export interface Player {
  id: number;
  name: string;
  team: string;
  position: Position;
  points: number;
  average_points: number;
  value: number;
  trend: Trend;
  streak: string[];
  status: PlayerStatus;
  has_team: boolean;
  /** Set by the lineup view when the player wears the armband. */
  isCaptain?: boolean;
}

export interface Finances {
  balance: number;
  max_bid: number;
}

export interface MarketSuggestion {
  type: 'free_agent' | 'steal';
  player_id: number;
  player_name: string;
  value: number;
  score: number;
  suggested_bid: number;
  reason: string;
  clause?: number;
  owner_id?: string;
}

/** A market suggestion enriched with the user's cart state. */
export interface BidItem extends MarketSuggestion {
  selected: boolean;
  ai_discard_reason?: string;
}

export interface SaleItem {
  player_id: number;
  player_name: string;
  value: number;
  suggested_price: number;
  /** 'accept' | 'renew' | undefined (plain sale) — set by the backend. */
  action?: string;
  id_bid?: string;
  id_market?: string;
  /** Why the engine decided this (e.g. offer accepted, no real-life club). */
  reason?: string;
}

export interface ProtectionItem {
  player_id: number;
  player_name: string;
  score: number;
  value: number;
  suggested_price: number;
  reason: string;
}

export interface Lineup {
  formation: string | null;
  score: number;
  /** Mister slot number (1-11) -> player id. */
  slots: Record<string, number>;
  captain_slot: number | null;
}

export interface WizardInitResponse {
  finances: Finances;
  market_suggestions: MarketSuggestion[];
  lineup: Lineup;
  squad: Player[];
  sales: SaleItem[];
  protections: ProtectionItem[];
  rival_players: Player[];
}

export interface AIVerdict {
  safe: boolean;
  reason: string;
}

export interface AIPrecheckResponse {
  verdicts: Record<string, AIVerdict>;
}

export type AIReviewStatus = 'OK' | 'SUGGESTIONS' | 'BAD' | 'ERROR';

export interface AIReview {
  status: AIReviewStatus;
  reason: string;
}

export interface ExecutePayload {
  bids: BidItem[];
  sales: SaleItem[];
  protections: ProtectionItem[];
  lineup: Lineup;
}

export interface ExecuteResponse {
  success: boolean;
  message: string;
}
