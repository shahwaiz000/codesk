export interface AuthStatus { auth_enabled: boolean; needs_setup: boolean; user: { username: string } | null }

export interface Driver {
  id: number; code: string; name: string; phone: string; hub: string; active: boolean; pos_terminal: string;
  last_collection: string | null; days_collected: number;
  cash_shortage: number; open_advances: number; open_advance_count: number;
}

export interface AuditEntry { id: number; at: string; username: string; action: string; entity: string; entity_id: number | null; summary: string }

export interface Meta { currency: string; latest_business_date: string | null; first_business_date: string | null; deposit_count: number }

export type CashStatus = "ok" | "short" | "over";

export interface Handover {
  id: number; business_date: string; driver_id: number; driver_code: string; driver_name: string; hub: string;
  orders: number; expected_cash: number; cash_received: number; difference: number; status: CashStatus;
  pos_amount: number; pos_terminal: string; total: number; note: string; created_by: string;
}

export interface DayTotals {
  expected_cash: number; cash_received: number; difference: number; short: number; over: number;
  short_count: number; over_count: number; pos_amount: number; total: number; orders: number; drivers: number;
}

export interface CollectionDay {
  date: string; rows: Handover[]; totals: DayTotals;
  missing: { id: number; code: string; name: string; hub: string }[];
}

export type PosStatus = "agrees" | "terminal_short" | "terminal_over" | "no_terminal";
export interface PosReview { status: "explained" | "follow_up"; note: string; by: string; at: string; stale: boolean }
export interface PosRow {
  driver_id: number; driver_code: string; driver_name: string; terminal: string | null;
  system_total: number; order_count: number; terminal_total: number | null; difference: number | null;
  status: PosStatus; status_text: string; review: PosReview | null; open: boolean;
}
export interface PosTotals {
  system_total: number; terminal_total: number; difference: number; order_count: number; drivers: number;
  agrees: number; differences: number; no_terminal: number; open: number; explained: number; short: number; over: number;
}
export interface PosDay { date: string; rows: PosRow[]; totals: PosTotals; orders_imported: boolean }
