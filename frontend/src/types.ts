export interface AuthStatus { auth_enabled: boolean; needs_setup: boolean; user: { username: string } | null }

export interface Driver {
  id: number; code: string; name: string; phone: string; hub: string; active: boolean;
  last_collection: string | null; days_collected: number;
  cash_shortage: number; open_advances: number; open_advance_count: number;
}

export interface AuditEntry { id: number; at: string; username: string; action: string; entity: string; entity_id: number | null; summary: string }

export interface Meta { currency: string; latest_business_date: string | null; first_business_date: string | null; deposit_count: number }
