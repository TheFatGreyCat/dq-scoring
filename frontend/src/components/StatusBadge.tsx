import {
  Ban,
  Bug,
  CircleCheck,
  CircleHelp,
  CircleMinus,
  Clock,
  Eye,
  EyeOff,
  LoaderCircle,
  OctagonX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { GovernanceStatus, MeasurementStatus, PublicationStatus, QualityGate, RunStatus } from "../api/types";
import { useI18n, type TranslationKey } from "../lib/i18n";
import type { SurfaceTranslationKey } from "../lib/surfaceTranslations";

type KnownBadgeKey = TranslationKey | SurfaceTranslationKey;


type Tone = "pass" | "warn" | "fail" | "error" | "neutral" | "info";

const TONE_CLASS: Record<Tone, string> = {
  pass: "text-pass bg-pass-bg",
  warn: "text-warn bg-warn-bg",
  fail: "text-fail bg-fail-bg",
  error: "text-error bg-error-bg",
  neutral: "text-neutral bg-neutral-bg",
  info: "text-info bg-info-bg",
};

interface Spec {
  tone: Tone;
  icon: LucideIcon;
  label: string;
  spin?: boolean;
}

/** Every status renders as text + icon + color; never color alone. */
export function Badge({ spec, size = "sm" }: { spec: Spec; size?: "sm" | "lg" }) {
  const Icon = spec.icon;
  const sizing = size === "lg" ? "text-base px-3 py-1.5 gap-2" : "text-xs px-2 py-1 gap-1.5";
  return (
    <span className={`inline-flex items-center rounded-full font-semibold whitespace-nowrap ${sizing} ${TONE_CLASS[spec.tone]}`}>
      <Icon aria-hidden className={`${size === "lg" ? "size-5" : "size-3.5"} ${spec.spin ? "animate-spin" : ""}`} />
      {spec.label}
    </span>
  );
}
interface BaseSpec {
  tone: Tone;
  icon: LucideIcon;
  key: string;
  spin?: boolean;
}

export const GATE: Record<QualityGate, BaseSpec> = {
  PASS: { tone: "pass", icon: CircleCheck, key: "gate.PASS" },
  WARN: { tone: "warn", icon: TriangleAlert, key: "gate.WARN" },
  FAIL: { tone: "fail", icon: OctagonX, key: "gate.FAIL" },
  ERROR: { tone: "error", icon: Bug, key: "gate.ERROR" },
  INSUFFICIENT_EVIDENCE: { tone: "neutral", icon: CircleHelp, key: "gate.INSUFFICIENT_EVIDENCE" },
};

export const RUN: Record<RunStatus, BaseSpec> = {
  QUEUED: { tone: "info", icon: Clock, key: "status.QUEUED" },
  LEASED: { tone: "info", icon: LoaderCircle, spin: true, key: "status.LEASED" },
  RUNNING: { tone: "info", icon: LoaderCircle, spin: true, key: "status.RUNNING" },
  SUCCEEDED: { tone: "pass", icon: CircleCheck, key: "status.SUCCEEDED" },
  FAILED: { tone: "fail", icon: OctagonX, key: "status.FAILED" },
  CANCELLED: { tone: "neutral", icon: Ban, key: "status.CANCELLED" },
};

export const MEASUREMENT: Record<MeasurementStatus, BaseSpec> = {
  MEASURED: { tone: "pass", icon: CircleCheck, key: "measurement.MEASURED" },
  NOT_APPLICABLE: { tone: "neutral", icon: CircleMinus, key: "measurement.NOT_APPLICABLE" },
  NOT_MEASURABLE: { tone: "neutral", icon: CircleHelp, key: "measurement.NOT_MEASURABLE" },
  FAILED_TO_MEASURE: { tone: "error", icon: Bug, key: "measurement.FAILED_TO_MEASURE" },
  INSUFFICIENT_DATA: { tone: "neutral", icon: CircleHelp, key: "measurement.INSUFFICIENT_DATA" },
  SKIPPED_BY_BUDGET: { tone: "warn", icon: Clock, key: "measurement.SKIPPED_BY_BUDGET" },
};

export const PUBLICATION: Record<PublicationStatus, BaseSpec> = {
  PUBLISHED: { tone: "pass", icon: Eye, key: "publication.PUBLISHED" },
  WITHHELD: { tone: "neutral", icon: EyeOff, key: "publication.WITHHELD" },
};

const GOVERNANCE: Record<string, BaseSpec> = {
  DRAFT: { tone: "neutral", icon: CircleMinus, key: "status.DRAFT" },
  PENDING_APPROVAL: { tone: "warn", icon: Clock, key: "status.PENDING_APPROVAL" },
  ACTIVE: { tone: "pass", icon: CircleCheck, key: "status.ACTIVE" },
};

export function specFor(
  table: Record<string, BaseSpec>,
  value: string,
  t?: (key: KnownBadgeKey) => string,
): Spec {
  const base = table[value];
  if (!base) {
    const unknownText = t ? t("common.unknown") : "Unknown";
    return { tone: "neutral", icon: CircleHelp, label: `${unknownText} (${value})` };
  }
  const label = t ? t(base.key as KnownBadgeKey) : base.key;
  return { tone: base.tone, icon: base.icon, spin: base.spin, label };
}


export const GateBadge = ({ gate, size }: { gate: QualityGate; size?: "sm" | "lg" }) => {
  const { t } = useI18n();
  return <Badge spec={specFor(GATE, gate, t)} size={size} />;
};
export const RunBadge = ({ status, size }: { status: RunStatus; size?: "sm" | "lg" }) => {
  const { t } = useI18n();
  return <Badge spec={specFor(RUN, status, t)} size={size} />;
};
export const MeasurementBadge = ({ status }: { status: MeasurementStatus }) => {
  const { t } = useI18n();
  return <Badge spec={specFor(MEASUREMENT, status, t)} />;
};
export const PublicationBadge = ({ status }: { status: PublicationStatus }) => {
  const { t } = useI18n();
  return <Badge spec={specFor(PUBLICATION, status, t)} />;
};
export const GovernanceBadge = ({ status }: { status: GovernanceStatus }) => {
  const { t } = useI18n();
  return <Badge spec={specFor(GOVERNANCE, status, t)} />;
};
