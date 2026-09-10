export type PlatformRole = "admin" | "staff" | "none";

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  platform_role: PlatformRole;
  is_active: boolean;
  created_at: string | null;
}

export interface AccessibleBusiness {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface MeResponse {
  user: User;
  businesses: AccessibleBusiness[];
  can_access_control_center: boolean;
  is_read_only: boolean;
}

export interface Business {
  id: string;
  name: string;
  slug: string;
  status: string;
  default_profile_key: string | null;
  is_demo: boolean;
  selection_mode: string;
  enabled_profiles: string[];
  modules: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ModuleEntitlement {
  key: string;
  label: string;
  icon: string;
  implemented: boolean;
  description: string;
  enabled: boolean;
}

export interface NavModule {
  key: string;
  label: string;
  icon: string;
  implemented: boolean;
  description: string;
}

export interface PhoneNumber {
  id: number;
  business_id: string;
  phone: string;
  label: string | null;
  enabled: boolean;
}

export interface Membership {
  id: number;
  business_id: string;
  user_id: string;
  role: string;
  user?: User;
}

export interface AuditEvent {
  id: number;
  business_id: string | null;
  actor_user_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
  created_at: string | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type LeadWorkflowStatus = "new" | "qualified" | "needs_review" | "scheduled" | "closed";

export interface Lead {
  id: number;
  phone: string;
  profile_key: string;
  customer_name: string | null;
  service_request: string | null;
  source: string | null;
  intake_data: Record<string, unknown>;
  intake_status: string;
  workflow_status: LeadWorkflowStatus;
  category: string | null;
  business_summary: string | null;
  client_notes: string | null;
  requested_callback_time: string | null;
  is_complete: boolean;
  archived_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** A metric the platform cannot honestly report yet, and why. */
export interface UnavailableMetric {
  key: string;
  reason: string;
}
