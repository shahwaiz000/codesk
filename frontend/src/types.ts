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

export interface ExpenseRow {
  id: number; business_date: string; driver_id: number; driver_code: string; driver_name: string;
  category: string; category_text: string; amount: number; reference: string; note: string; created_by: string;
  settled_on: string | null; settlement_method: "salary" | "cash" | null; settlement_note: string; days_open?: number;
}
export interface ExpenseDay {
  date: string; rows: ExpenseRow[];
  totals: { expenses: number; advances: number; total: number; count: number; by_category: { category: string; category_text: string; amount: number }[] };
  categories: { value: string; text: string }[];
}
export interface Advances { rows: ExpenseRow[]; open_total: number; open_count: number; drivers: number }

export type DepositStatus = "deposited" | "not_due" | "due_today" | "overdue" | "short" | "over" | "nothing";
export interface Slip { id: number; deposit_date: string; bank: string; slip_ref: string; amount: number; note: string; created_by: string }
export interface DepositDay {
  date: string; due_on: string; cash_received: number; paid_out: number; returned: number; to_deposit: number;
  deposited: number; pending: number; status: DepositStatus; status_text: string; late: boolean; days_late: number; slips: Slip[];
}
export interface DepositLedger {
  rows: DepositDay[]; banks: string[]; today: string;
  totals: { cash_on_hand: number; overdue: number; overdue_days: number; short: number; short_days: number; due_today: number; not_due: number; deposited: number; late_days: number };
}
