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

export interface MissedCallEvent {
  id: number;
  caller_phone: string;
  twilio_number: string;
  forwarded_from: string | null;
  source: string;
  decision: string;
  message_sid: string | null;
  call_status: string | null;
  call_duration_seconds: number | null;
  delivery_status: string | null;
  send_attempts: number;
  last_attempt_at: string | null;
  error_code: string | null;
  archived_at: string | null;
  created_at: string | null;
}

export interface CalendarConnection {
  provider: "google";
  calendar_id: string;
  calendar_name: string;
  timezone: string;
  verified_at: string | null;
  default_duration_minutes: number;
  connected: boolean;
  credentials_configured: boolean;
  service_account_email: string | null;
}

export type AppointmentStatus =
  | "pending"
  | "scheduled"
  | "declined"
  | "cancelled"
  | "sync_failed";

export interface AppointmentRequest {
  id: number;
  business_id: string;
  lead_id: number | null;
  customer_name: string | null;
  customer_phone: string;
  service_request: string | null;
  requested_time_text: string | null;
  scheduled_start_at: string | null;
  duration_minutes: number;
  status: AppointmentStatus;
  calendar_event_id: string | null;
  calendar_event_link: string | null;
  provider_error: string | null;
  created_at: string | null;
  updated_at: string | null;
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

export type ConversationState =
  | "awaiting_profile_selection"
  | "in_progress"
  | "completed"
  | "terminated";

export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ConversationSummary {
  id: number;
  phone: string;
  customer_name: string | null;
  profile_key: string | null;
  state: ConversationState;
  turn_count: number;
  off_topic_strikes: number;
  terminated: boolean;
  opted_out: boolean;
  requested_callback_time: string | null;
  message_count: number;
  last_message: string;
  created_at: string | null;
  updated_at: string | null;
  expires_at: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
  collected_fields: Record<string, unknown>;
}

/** A metric the platform cannot honestly report yet, and why. */
export interface UnavailableMetric {
  key: string;
  reason: string;
}
