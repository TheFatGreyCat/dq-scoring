// Hand-mirrored from src/dq_scoring/presentation/api/schemas/*.py and core enums.
// Replace with an OpenAPI-generated client once the API contract is stable.

export type UUID = string;

export type QualityGate = "ERROR" | "FAIL" | "INSUFFICIENT_EVIDENCE" | "WARN" | "PASS";
export type PublicationStatus = "PUBLISHED" | "WITHHELD";
export type MeasurementStatus =
  | "MEASURED"
  | "NOT_APPLICABLE"
  | "NOT_MEASURABLE"
  | "FAILED_TO_MEASURE"
  | "INSUFFICIENT_DATA"
  | "SKIPPED_BY_BUDGET";
export type RunStatus = "QUEUED" | "LEASED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
export type GovernanceStatus = "DRAFT" | "PENDING_APPROVAL" | "ACTIVE" | (string & {});

export const DIMENSIONS = [
  "ACCURACY",
  "COMPLETENESS",
  "CONSISTENCY",
  "TIMELINESS",
  "VALIDITY",
  "UNIQUENESS",
] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ["SUCCEEDED", "FAILED", "CANCELLED"];

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
}

export interface AssetResponse {
  asset_id: UUID;
  tenant_id: UUID;
  name: string;
  created_at: string;
  format?: string;
  current_snapshot_id?: UUID | null;
  version_count?: number;
}

export interface SnapshotResponse {
  asset_id: UUID;
  source_kind: string;
  source_descriptor: Record<string, unknown>;
  schema_definition: Record<string, unknown>;
  total_rows: number;
  total_columns: number;
  snapshot_id: UUID;
  tenant_id: UUID;
  captured_at: string;
}

export interface QualityRuleInput {
  rule_code: string;
  dimension: Dimension;
  rule_type: string;
  parameters: Record<string, unknown>;
  null_policy: string;
  is_required: boolean;
  is_critical: boolean;
  gate_enabled: boolean;
  score_enabled: boolean;
  contribution_weight: number;
  acceptance_threshold: number | null;
  is_advisory: boolean;
}

export interface QualityRuleResponse extends QualityRuleInput {
  rule_id: UUID;
}

export interface RulesetResponse {
  ruleset_id: UUID;
  tenant_id: UUID;
  asset_id: UUID;
  name: string;
  status: GovernanceStatus;
  current_version: number;
  created_by: UUID;
  created_at: string;
  rules: QualityRuleResponse[];
}

export interface CreatePolicyRequest {
  name: string;
  gate_fail_threshold: number;
  gate_warn_threshold: number;
  min_coverage_threshold: number;
  critical_acceptance_threshold: number | null;
  dimension_weights: Record<string, number>;
}

export interface PolicyResponse extends CreatePolicyRequest {
  policy_id: UUID;
  tenant_id: UUID;
  status: GovernanceStatus;
  current_version: number;
  created_by: UUID;
  created_at: string;
}

export interface TriggerRunRequest {
  snapshot_id: UUID;
  ruleset_id: UUID;
  policy_id: UUID;
  execution_profile: string;
  outlier_columns: string[];
  idempotency_key: string;
}

export interface RunResponse {
  run_id: UUID;
  tenant_id: UUID;
  snapshot_id: UUID;
  ruleset_id: UUID;
  policy_id: UUID;
  status: RunStatus;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
  assessment_id?: UUID | null;
}

export interface RunStatusResponse {
  run_id: UUID;
  status: RunStatus;
  error_message: string | null;
  assessment_id: UUID | null;
  updated_at: string | null;
  created_at: string; started_at: string | null; completed_at: string | null; heartbeat_at: string | null; attempt_count: number;
}

export interface RuleResult {
  /** null for advisory signals (IQR outliers) that are not configured rules. */
  rule_id: UUID | null;
  rule_code: string;
  dimension: string;
  target_column: string;
  rule_type: string;
  measurement_status: MeasurementStatus;
  computed_score: number | null;
  passed_count: number;
  failed_count: number;
  missing_count: number;
  miscast_count: number;
  not_applicable_count: number;
  total_observed: number;
  violations_count: number;
  weight: number;
  is_required: boolean;
  is_critical: boolean;
  is_advisory: boolean;
  evidence_samples: Record<string, unknown>[] | null;
  error_message: string | null;
}

export interface DimensionResult {
  dimension: string;
  dimension_score: number | null;
  coverage_ratio: number | null;
  dimension_weight?: number;
}

export interface AssessmentDetail {
  assessment_id: UUID;
  tenant_id: UUID;
  run_id: UUID;
  snapshot_id: UUID;
  dq_score: number | null;
  publication_status: PublicationStatus;
  coverage_ratio: number | null;
  quality_gate: QualityGate;
  assessment_hash: string;
  created_at: string;
  dimension_results: DimensionResult[];
  rule_results: RuleResult[];
}

export interface PublicAssessment {
  assessment_id: UUID;
  dq_score: number | null;
  publication_status: PublicationStatus;
  coverage_ratio: number | null;
  quality_gate: QualityGate;
  assessment_hash: string;
  created_at: string;
  dimensions: DimensionResult[];
}

/** RFC 9457 problem details as emitted by presentation/api/errors.py. */
export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  invalid_params?: { name: string; reason: string; code?: string; params?: Record<string, string | number> }[];
  error_code?: string;
  reason?: string;
  max_failed_attempts?: number;
  locked_until?: string;
  retry_after_seconds?: number;
}

export interface RuleCatalogTemplate {
  template_id: UUID;
  template_code: string;
  name: string;
  rule_type: string;
  parameter_schema: Record<string, unknown>;
  default_null_policy: string;
  default_dimension: Dimension;
  is_advisory_default: boolean;
}

export interface RulesetTemplate {
  template_id: UUID;
  template_code: string;
  name: string;
  domain: string;
  data_type: string;
  target_use_case: string;
  description?: string;
  rules_payload: Array<Record<string, unknown>>;
  is_system_template: boolean;
}

export interface ScoringPolicyTemplate {
  template_id: UUID;
  template_code: string;
  name: string;
  domain: string;
  target_use_case: string;
  description?: string;
  dimension_weights: Record<string, number>;
  publication_threshold: number;
  gate_rules: Record<string, unknown>;
  is_system_template: boolean;
}

export interface TemplateOverview {
  total_rule_templates: number;
  total_ruleset_templates: number;
  total_policy_templates: number;
  supported_domains: string[];
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number; }
export interface ImportSession {
  upload_id: UUID; status: string; format: string; part_size: number; part_count: number;
  size_bytes: number; original_filename: string; completed_parts?: number[];
  asset_id?: UUID | null; asset_name?: string | null; snapshot_id?: UUID | null;
  error_code?: string | null; invalid_params?: { name: string; reason: string; code?: string }[];
  completed_part_details?: {part_number: number; etag: string}[];
  schema_definition: Record<string, unknown>; source_descriptor: Record<string, unknown>;
  total_rows?: number | null; total_columns?: number | null;
  warnings?: string[]; preview?: Record<string, unknown>[]; profile?: Record<string, unknown>;
  created_at: string; updated_at: string; expires_at: string; csv_options: {delimiter: string; encoding: string} | null;
}
export interface StorageObject { bucket: string; key: string; size_bytes: number; last_modified?: string; }
export interface DatasetPreview {
  schema_definition: Record<string, unknown>; preview: Record<string, unknown>[];
  profile: Record<string, unknown>; warnings: string[]; total_rows: number; total_columns: number;
  source_descriptor: Record<string, unknown>;
}
export interface Recommendations {
  rules: { rule: QualityRuleInput; reason_code: string; reason_params: Record<string, unknown>; sample_rows: number; is_sample: boolean }[];
  ruleset_templates: { template_id: string; score: number; matched_columns: string[]; missing_columns: string[] }[];
  policy_templates: { template_id: string; reason_code: string }[]; warnings: string[];
}

export interface CurrentUser { user_id: UUID; tenant_id: UUID; email: string; role: string; }
export type ComponentStatus = "up" | "down" | "degraded" | "unknown";
export interface SparkSizing { driver_memory: string; executor_memory: string; executor_instances: number; executor_cores: number; max_memory_mb: number; sql_shuffle_partitions: number; }
export interface OperationsMonitorResponse {
  checked_at: string;
  components: { api: ComponentStatus; database: ComponentStatus; storage: ComponentStatus; spark_master: ComponentStatus };
  workers: { worker_id: string; kind: "IMPORT" | "EVALUATION"; started_at: string; heartbeat_at: string; status: "initializing" | "ready" | "busy" | "degraded" | "stale"; last_error_code: string | null; metrics: { mode?: string | null; sizing?: SparkSizing | null; executors?: {id: string; active: boolean; cores: number; active_tasks: number; completed_tasks: number}[] | null } }[];
  spark: { mode: string | null; expected_executors: number | null; active_executors: number | null; active_jobs: number | null; active_stages: number | null; workers: {id: string; state: string; cores: number; allocated_cores: number; memory_mib: number; allocated_memory_mib: number}[] };
  queue: { queued: number | null; active: number | null; failed_24h: number | null; oldest_queued_at: string | null };
  warnings: string[];
}
export interface OperationsConfigResponse { configured_only: true; imports: {formats: string[]; max_bytes: number; part_bytes: number; max_columns: number}; deployment: SparkSizing; reported_workers: {worker_id: string; sizing: SparkSizing}[]; }
export interface OverviewResponse { checked_at: string; counts: {assets: number; snapshots: number; runs: Record<RunStatusResponse["status"], number>; rulesets_pending: number; policies_pending: number}; recent_runs: RunResponse[]; import_counts: Record<string,number> | null; recent_imports: ImportSessionSummary[] | null; }
export interface ImportSessionSummary { upload_id: UUID; status: string; asset_id: UUID | null; asset_name: string | null; format: string; original_filename: string; size_bytes: number; error_code: string | null; snapshot_id: UUID | null; created_at: string; updated_at: string; expires_at: string; }

export type FindingStatus = "DETECTED" | "CONFIRMED" | "DISMISSED";
export type FindingCategory = "BASIC_PERSONAL_DATA" | "SENSITIVE_PERSONAL_DATA" | "CONFIDENTIAL_BUSINESS_DATA";

export type PrivacyCategory = "STANDARD_DATA" | FindingCategory;
export type ScanStatus = "COMPLETE" | "UNAVAILABLE" | "QUEUED" | "RUNNING" | "FAILED";

export interface FindingResponse {
  finding_id: UUID;
  column_name: string;
  path: string;
  category: FindingCategory;
  detector_code: string;
  matched_count: number;
  observed_count: number;
  status: FindingStatus;
  detector_revision: string;
  method: string;
  rule_id?: UUID | null;
  rule_revision?: number | null;
  scan_id?: UUID | null;
  historical?: boolean;
}

export interface SensitiveFindingsResponse {
  scan_status: ScanStatus;
  detector_revision: string | null;
  scan_id?: UUID | null;
  scan_stale?: boolean;
  scanned_at?: string | null;
  config_version?: number | null;
  active_config_version?: number | null;
  findings: Page<FindingResponse>;
}

export interface ProtectionPolicyResponse {
  asset_id: UUID;
  version: number;
  categories: FindingCategory[];
  unsupported_policies: number;
}

export interface ColumnClassification {
  column_name: string;
  declared_category: PrivacyCategory | null;
  detected_categories: PrivacyCategory[];
  effective_categories: PrivacyCategory[];
  protected: boolean;
  conflict: boolean;
  reason: string | null;
}

export interface ColumnClassificationsResponse {
  asset_id: UUID;
  snapshot_id: UUID;
  version: number;
  scan_status: ScanStatus;
  scan_stale: boolean;
  columns: ColumnClassification[];
}

export interface ClassificationChange { column_name: string; category: PrivacyCategory | null; reason: string; }
export interface UpdateClassificationsRequest { snapshot_id: UUID; expected_version: number; changes: ClassificationChange[]; }

/** Per-column sample statistics emitted by the importer (counts are over `sample_rows`, not the full dataset). */
export interface ColumnProfile {
  name: string;
  type_hint: string;
  null_count: number;
  non_null_count: number;
  distinct_count: number;
  parse_success_count: number;
  sample_rows: number;
  timestamp_format?: string;
  min?: string | number;
  max?: string | number;
}
export interface DatasetProfile { sample_rows: number; is_sample: boolean; total_rows: number; columns: ColumnProfile[]; }
export interface SchemaColumn { name: string; original_name?: string; type?: string; structural_encoding?: string; logical_types?: string[]; }

export type PrivacyRuleKind = "BUILTIN" | "COLUMN_NAME" | "VALUE_PATTERN";
export type PrivacyMatchMode = "FULL" | "SEARCH";

export interface PrivacyRule {
  rule_id: UUID;
  revision: number;
  code: string;
  kind: PrivacyRuleKind;
  category: FindingCategory;
  enabled: boolean;
  builtin_code: string | null;
  pattern: string | null;
  match_mode: PrivacyMatchMode;
  case_sensitive: boolean;
  columns: string[];
  created_by: UUID | null;
  created_at: string;
}
export interface PrivacyRuleWriteResponse extends PrivacyRule { config_version: number; }
interface PrivacyRuleBody {
  category: FindingCategory;
  enabled: boolean;
  pattern: string | null;
  match_mode: PrivacyMatchMode;
  case_sensitive: boolean;
  columns: string[];
}
export interface PrivacyRuleCreateRequest extends PrivacyRuleBody {
  code: string;
  kind: Exclude<PrivacyRuleKind, "BUILTIN">;
  pattern: string;
}
export interface PrivacyRuleUpdateRequest extends PrivacyRuleBody { expected_revision: number; }

export type PrivacyScanState = "QUEUED" | "RUNNING" | "COMPLETE" | "FAILED";
export type PrivacyScanRequest = { purpose: "APPLY" } | { purpose: "PREVIEW"; rule_id: UUID; revision: number };
export interface PrivacyScanFindingSummary {
  column_name: string;
  path: string;
  category: FindingCategory;
  detector_code: string;
  rule_id: UUID | null;
  rule_revision: number | null;
  matched_count: number;
  observed_count: number;
  method: string;
}
export interface PrivacyScanSummary {
  total_rows?: number;
  finding_count?: number;
  columns_with_findings?: number;
  truncated?: boolean;
  findings?: PrivacyScanFindingSummary[];
  sensitive_columns?: string[];
  scope_missing_columns?: { rule_id: UUID; rule_revision: number; detector_code: string; missing_columns: string[] }[];
}
export interface PrivacyScan {
  scan_id: UUID;
  snapshot_id: UUID;
  purpose: "APPLY" | "PREVIEW";
  state: PrivacyScanState;
  config_version: number;
  detector_digest: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  result_summary: PrivacyScanSummary | null;
}
