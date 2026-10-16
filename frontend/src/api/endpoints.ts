import { api, session } from "./client";
import type {
  CurrentUser, OperationsMonitorResponse, OperationsConfigResponse, OverviewResponse,
  ImportSessionSummary,
  AssessmentDetail,
  AssetResponse,
  CreatePolicyRequest,
  PolicyResponse,
  PublicAssessment,
  QualityRuleInput,
  RulesetResponse,
  RunResponse,
  RunStatusResponse,
  SnapshotResponse,
  TokenResponse,
  TriggerRunRequest,
  UUID,
  RuleCatalogTemplate,
  RulesetTemplate,
  ScoringPolicyTemplate,
  Page, ImportSession, StorageObject, DatasetPreview, Recommendations,
  TemplateOverview, FindingCategory, FindingResponse, SensitiveFindingsResponse, ProtectionPolicyResponse,
  ColumnClassificationsResponse, UpdateClassificationsRequest,
  PrivacyRule, PrivacyRuleCreateRequest, PrivacyRuleUpdateRequest, PrivacyRuleWriteResponse,
  PrivacyScan, PrivacyScanFindingSummary, PrivacyScanRequest,
} from "./types";

const id = (value: UUID) => encodeURIComponent(value);

export async function login(email: string, password: string, tenantId?: UUID) {
  const res = await api<TokenResponse>("POST", "/auth/login", {
    body: { email, password, tenant_id: tenantId || null },
    auth: false,
  });
  session.set(res, email);
}

export async function logout() {
  const refresh = session.refreshToken();
  try {
    if (refresh) await api<void>("POST", "/auth/logout", { body: { refresh_token: refresh } });
  } finally {
    session.clear();
  }
}

export const createAsset = (name: string) => api<AssetResponse>("POST", "/assets", { body: { name } });


export const getSnapshot = (snapshotId: UUID, signal?: AbortSignal) =>
  api<SnapshotResponse>("GET", `/snapshots/${id(snapshotId)}`, { signal });

export const createRuleset = (body: { asset_id: UUID; name: string; rules: QualityRuleInput[] }) =>
  api<RulesetResponse>("POST", "/rulesets", { body });

export const createPolicy = (body: CreatePolicyRequest) => api<PolicyResponse>("POST", "/policies", { body });

export type GovernanceKind = "rulesets" | "policies";

export const submitForApproval = <T>(kind: GovernanceKind, entityId: UUID, notes: string) =>
  api<T>("POST", `/${kind}/${id(entityId)}/submit`, { body: { notes: notes || null } });

export const approve = <T>(kind: GovernanceKind, entityId: UUID, notes: string) =>
  api<T>("POST", `/${kind}/${id(entityId)}/approve`, { body: { approval_notes: notes || null } });

export const triggerRun = (body: TriggerRunRequest) => api<RunResponse>("POST", "/runs", { body });

export const getRunStatus = (runId: UUID, signal?: AbortSignal) =>
  api<RunStatusResponse>("GET", `/runs/${id(runId)}/status`, { signal });

export const getAssessment = (assessmentId: UUID, signal?: AbortSignal) =>
  api<AssessmentDetail>("GET", `/assessments/${id(assessmentId)}`, { signal });

export const getPublicAssessment = (assessmentId: UUID, signal?: AbortSignal) =>
  api<PublicAssessment>("GET", `/assessments/${id(assessmentId)}/public`, { signal, auth: false });

export type Filters = Record<string, string | number | undefined>;
const query = (filters: Filters = {}) => {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== "") params.set(key, String(value)); });
  return params.size ? `?${params}` : "";
};
export const listAssets = (filters: Filters = {}, signal?: AbortSignal) => api<Page<AssetResponse>>("GET", `/assets${query(filters)}`, { signal });
export const listSnapshots = (filters: Filters = {}, signal?: AbortSignal) => api<Page<SnapshotResponse>>("GET", `/snapshots${query(filters)}`, { signal });
export const listRulesets = (filters: Filters = {}, signal?: AbortSignal) => api<Page<RulesetResponse>>("GET", `/rulesets${query(filters)}`, { signal });
export const listPolicies = (filters: Filters = {}, signal?: AbortSignal) => api<Page<PolicyResponse>>("GET", `/policies${query(filters)}`, { signal });
export const listRuns = (filters: Filters = {}, signal?: AbortSignal) => api<Page<RunResponse>>("GET", `/runs${query(filters)}`, { signal });
export const listAssessments = (filters: Filters = {}, signal?: AbortSignal) => api<Page<Omit<AssessmentDetail, "dimension_results" | "rule_results"> & {published_at: string}>>("GET", `/assessments${query(filters)}`, { signal });
export const getRuleset = (value: UUID) => api<RulesetResponse>("GET", `/rulesets/${id(value)}`);
export const getPolicy = (value: UUID) => api<PolicyResponse>("GET", `/policies/${id(value)}`);
export const getRuleCatalogTemplates = (filters: Filters = {}, signal?: AbortSignal) => api<Page<RuleCatalogTemplate>>("GET", `/templates/rules${query(filters)}`, { signal });
export const getRulesetTemplates = (filters: Filters = {}, signal?: AbortSignal) => api<Page<RulesetTemplate>>("GET", `/templates/rulesets${query(filters)}`, { signal });
export const getPolicyTemplates = (filters: Filters = {}, signal?: AbortSignal) => api<Page<ScoringPolicyTemplate>>("GET", `/templates/policies${query(filters)}`, { signal });
export const getRulesetTemplate = (value: UUID) => api<RulesetTemplate>("GET", `/templates/rulesets/${id(value)}`);
export const getPolicyTemplate = (value: UUID) => api<ScoringPolicyTemplate>("GET", `/templates/policies/${id(value)}`);
export const createImport = (body: Record<string, unknown>) => api<ImportSession>("POST", "/imports", { body });
export const getImport = (value: UUID, signal?: AbortSignal) => api<ImportSession>("GET", `/imports/${id(value)}`, { signal });
export const uploadPart = (value: UUID, part: number, body: Blob, signal: AbortSignal) => api<{etag: string}>("POST", `/imports/${id(value)}/parts/${part}`, { body, binary: true, signal });
export const completeImport = (value: UUID, parts: {part_number: number; etag: string}[]) => api<ImportSession>("POST", `/imports/${id(value)}/complete`, { body: { parts } });
export const configureImport = (value: UUID, column_names: string[]) => api<ImportSession>("POST", `/imports/${id(value)}/configure`, { body: { column_names } });
export const registerImport = (value: UUID, acknowledged_warnings: string[]) => api<SnapshotResponse>("POST", `/imports/${id(value)}/register`, { body: { acknowledged_warnings } });
export const abortImport = (value: UUID) => api<ImportSession>("POST", `/imports/${id(value)}/abort`);
export const storageObjects = (filters: Filters = {}, signal?: AbortSignal) => api<{items: StorageObject[]; next_token: string | null}>("GET", `/storage/objects${query(filters)}`, { signal });
export const getPreview = (value: UUID) => api<DatasetPreview>("GET", `/snapshots/${id(value)}/preview`);
export const getRecommendations = (value: UUID, filters: Filters = {}) => api<Recommendations>("GET", `/snapshots/${id(value)}/recommendations${query(filters)}`);

export const getTemplateOverview = (signal?: AbortSignal) =>
  api<TemplateOverview>("GET", "/templates/overview", { signal });

export const getCurrentUser = (signal?: AbortSignal) => api<CurrentUser>("GET", "/auth/me", { signal });
export const getOperationsMonitor = (signal?: AbortSignal) => api<OperationsMonitorResponse>("GET", "/operations/monitor", { signal });
export const getOperationsConfig = (signal?: AbortSignal) => api<OperationsConfigResponse>("GET", "/operations/config", { signal });
export const getOverview = (signal?: AbortSignal) => api<OverviewResponse>("GET", "/overview", { signal });
export const listImports = (filters: Filters = {}, signal?: AbortSignal) => api<Page<ImportSessionSummary>>("GET", `/imports${query(filters)}`, { signal });

export const getSensitiveFindings = (snapshotId: UUID, filters: Filters = {}, signal?: AbortSignal) =>
  api<SensitiveFindingsResponse>("GET", `/snapshots/${id(snapshotId)}/sensitive-findings${query(filters)}`, { signal });

export const updateFindingStatus = (findingId: UUID, expectedStatus: string, status: string, reason: string) =>
  api<FindingResponse>("PATCH", `/sensitive-findings/${id(findingId)}`, { body: { expected_status: expectedStatus, status, reason } });

export const getProtectionPolicy = (assetId: UUID, signal?: AbortSignal) =>
  api<ProtectionPolicyResponse>("GET", `/assets/${id(assetId)}/protection-policy`, { signal });

export const updateProtectionPolicy = (assetId: UUID, expectedVersion: number, categories: FindingCategory[]) =>
  api<ProtectionPolicyResponse>("PUT", `/assets/${id(assetId)}/protection-policy`, {
    body: { expected_version: expectedVersion, categories },
  });

export const getColumnClassifications = (snapshotId: UUID, signal?: AbortSignal) =>
  api<ColumnClassificationsResponse>("GET", `/snapshots/${id(snapshotId)}/column-classifications`, { signal });

export const updateColumnClassifications = (assetId: UUID, body: UpdateClassificationsRequest) =>
  api<ColumnClassificationsResponse>("PUT", `/assets/${id(assetId)}/column-classifications`, { body });

export const listPrivacyRules = (filters: Filters = {}, signal?: AbortSignal) =>
  api<Page<PrivacyRule>>("GET", `/privacy-rules${query(filters)}`, { signal });

export const createPrivacyRule = (body: PrivacyRuleCreateRequest) =>
  api<PrivacyRuleWriteResponse>("POST", "/privacy-rules", { body });

export const updatePrivacyRule = (ruleId: UUID, body: PrivacyRuleUpdateRequest) =>
  api<PrivacyRuleWriteResponse>("PUT", `/privacy-rules/${id(ruleId)}`, { body });

export const createPrivacyScan = (snapshotId: UUID, body: PrivacyScanRequest) =>
  api<PrivacyScan>("POST", `/snapshots/${id(snapshotId)}/privacy-scans`, { body });

export const getPrivacyScan = (scanId: UUID, signal?: AbortSignal) =>
  api<PrivacyScan>("GET", `/privacy-scans/${id(scanId)}`, { signal });

export const getPrivacyScanFindings = (scanId: UUID, filters: Filters = {}, signal?: AbortSignal) =>
  api<Page<PrivacyScanFindingSummary>>("GET", `/privacy-scans/${id(scanId)}/findings${query(filters)}`, { signal });

export const getMaskedExportUrl = (assetId: UUID, snapshotId: UUID) =>
  `/api/v1/assets/${id(assetId)}/masked-export?snapshot_id=${id(snapshotId)}`;

/** Downloads the snapshot-specific masked export; failures surface as ApiError (never a substitute file). */
export const downloadMaskedExport = (assetId: UUID, snapshotId: UUID, signal?: AbortSignal) =>
  api<Blob>("GET", `/assets/${id(assetId)}/masked-export?snapshot_id=${id(snapshotId)}`, {
    signal,
    responseType: "blob",
  });
