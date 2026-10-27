export interface AuthStatus { auth_enabled: boolean; needs_setup: boolean; user: { username: string } | null }

export interface Driver {
  id: number; code: string; name: string; phone: string; hub: string; active: boolean;
  last_collection: string | null; days_collected: number;
  cash_shortage: number; open_advances: number; open_advance_count: number;
}

export interface AuditEntry { id: number; at: string; username: string; action: string; entity: string; entity_id: number | null; summary: string }

export interface Meta { currency: string; latest_business_date: string | null; first_business_date: string | null; deposit_count: number }

export type CashStatus = "ok" | "short" | "over";

export interface Handover {
  id: number; business_date: string; driver_id: number; driver_code: string; driver_name: string; hub: string;
  orders: number; expected_cash: number; cash_received: number; difference: number; status: CashStatus;
  pos_amount: number; total: number; note: string; created_by: string;
}

export interface DayTotals {
  expected_cash: number; cash_received: number; difference: number; short: number; over: number;
  short_count: number; over_count: number; pos_amount: number; total: number; orders: number; drivers: number;
}

export interface CollectionDay {
  date: string; rows: Handover[]; totals: DayTotals;
  missing: { id: number; code: string; name: string; hub: string }[];
}

export type ImportStatus = "new" | "update" | "same" | "error";
export interface ImportRow {
  line: number; status: ImportStatus; problems: string[]; driver_code: string | null; driver_name: string;
  date: string | null; orders: number; expected_cash: number; cash_received: number; pos_amount: number; difference: number; note: string;
}
export interface ImportResult {
  file: string; rows: ImportRow[]; counts: Record<ImportStatus, number>; committed: boolean; saved: number; dates: string[];
}
