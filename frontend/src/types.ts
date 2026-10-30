export interface AuthStatus { auth_enabled: boolean; needs_setup: boolean; user: { username: string } | null }

export interface Driver {
  id: number; code: string; name: string; phone: string; hub: string; active: boolean; pos_terminal: string;
  last_collection: string | null; days_collected: number;
  station_id: number | null; station: string; station_code: string;
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

export type PosStatus = "agrees" | "terminal_short" | "terminal_over" | "no_terminal" | "awaiting_orders";
export interface PosReview { status: "explained" | "follow_up"; note: string; by: string; at: string; stale: boolean }
export interface PosRow {
  driver_id: number; driver_code: string; driver_name: string; terminal: string | null;
  system_total: number; order_count: number; terminal_total: number | null; difference: number | null;
  status: PosStatus; status_text: string; review: PosReview | null; open: boolean; paired_by?: PairedBy | null;
}
export type PairedBy = "terminal" | "amount" | "hand";
export interface Machine {
  id: number; terminal: string; amount: number; driver_id: number | null; driver_code: string | null; driver_name: string | null;
  paired_by: PairedBy | null;
  suggestions: { driver_id: number; driver_code: string; driver_name: string; system_total: number; difference: number }[];
}
export interface PosTotals {
  system_total: number; terminal_total: number; difference: number; order_count: number; drivers: number;
  agrees: number; differences: number; no_terminal: number; awaiting: number; open: number; explained: number; short: number; over: number;
  sheet?: boolean; machines?: number; machines_total?: number; unpaired?: number; unpaired_total?: number; drivers_without_machine?: number;
}
export interface PosDay { date: string; rows: PosRow[]; totals: PosTotals; orders_imported: boolean; machines?: Machine[] }

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
  deposited: number; pending: number; rounding?: number; status: DepositStatus;
  brought_forward: number; total_due: number; left: number; paid_later_on?: string | null;
  station_id?: number | null; station?: string; station_code?: string; status_text: string; late: boolean; days_late: number; slips: Slip[];
}
export interface DepositLedger {
  rows: DepositDay[]; banks: string[]; today: string;
  totals: { cash_on_hand: number; overdue: number; overdue_days: number; short: number; short_days: number; due_today: number; not_due: number; deposited: number; late_days: number };
}

export interface DashFigures {
  cash_received: number; expected_cash: number; cash_short: number; cash_over: number; short_count: number; over_count: number;
  pos_terminal: number; pos_system: number; pos_difference: number; pos_open: number; pos_differences: number; pos_awaiting?: number;
  total_collected: number; orders: number; drivers: number; expenses: number; advances: number;
  paid_out: number; returned: number; to_deposit: number; deposited: number; pending: number;
  deposit_status: DepositStatus; deposit_status_text: string; due_on: string | null;
  brought_forward?: number; total_due?: number; left?: number;
}
export interface DashIssue { kind: "cash_short" | "cash_over" | "terminal_short" | "terminal_over"; amount: number; page: string; explained?: boolean }
export interface DashAlert { kind: string; date: string; amount: number; page: string; text: string }
export interface Dashboard {
  date: string; previous_date: string | null; figures: DashFigures; previous: DashFigures | null; active_drivers: number;
  cash_on_hand: number; attention: { driver_code: string; driver_name: string; issues: DashIssue[] }[];
  alerts: DashAlert[]; alert_count: number; alert_kinds: Record<string, number>;
  trend: { date: string; cash: number; pos: number; deposit_status: DepositStatus }[];
}
export interface ReportPreview {
  start: string; end: string; days: number; handovers: number; cash_differences: number; pos_differences: number;
  expenses: number; slips: number; open_advances: number; pending_days: number;
  totals: { expected_cash: number; cash_received: number; cash_difference: number; pos_system: number; pos_terminal: number;
    pos_difference: number; paid_out: number; returned: number; to_deposit: number; deposited: number; pending: number };
}

export interface Unusual {
  key: string; kind: "unusual_expense" | "unusual_payout" | "unusual_pos"; date: string; driver_code: string | null; driver_name: string | null;
  amount: number; usual: number | null; ratio: number | null; page: string; text: string; expense_id?: number;
  review: { note: string; by: string } | null;
}

export interface AiStatus {
  engine: "local" | "gemini"; demo_mode: boolean; gemini_model: string; has_key: boolean; key_hint: string; ack: boolean;
  ready: boolean; reason: string;
}

export interface Station { id: number; code: string; name: string; city: string; region: string; active: boolean; drivers: number }
export interface StationList { stations: Station[]; unassigned_drivers: number }
export interface StationDay extends Station {
  handed_over: number; cash_received: number; pos_system: number; pos_terminal: number; pos_difference: number; pos_open: number;
  paid_out: number; to_deposit: number; deposited: number; pending: number; deposit_status: DepositStatus; deposit_status_text: string;
  cash_on_hand: number; late_days: number; late_amount: number; late_dates: string[];
  files: { report: boolean; pos_orders: boolean; terminal_sheet: boolean; expenses: number; slip: "sent" | "waiting" | "missing" | "none" };
  problems: { level: "call" | "check"; text: string }[]; level: "call" | "check" | "ok";
}
export interface StationOverview {
  date: string; stations: StationDay[]; active_stations: number;
  totals: { cash_received: number; pos_system: number; pos_terminal: number; paid_out: number; to_deposit: number; deposited: number;
    pending: number; cash_on_hand: number; late_amount: number; late_days: number };
}
