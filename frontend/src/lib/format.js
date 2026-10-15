export const FIELD_LABELS = {
  equipmentModel: "Equipment Model",
  serialNumber: "Serial Number",
  category: "Issue Category",
  symptom: "Symptom",
  suspectedCause: "Root Cause",
  affectedPart: "Affected Part",
  severity: "Severity",
  resolution: "Resolution",
  warrantyRelevance: "Warranty",
};

export const STATUS_META = {
  PROCESSING: { label: "Processing", tone: "neutral" },
  NEEDS_REVIEW: { label: "Needs Review", tone: "warn" },
  READY_FOR_APPROVAL: { label: "Ready for Approval", tone: "info" },
  APPROVED: { label: "Approved", tone: "ok" },
  ESCALATED: { label: "Escalated", tone: "bad" },
};

export const SOURCE_LABELS = {
  AI_VALIDATED: "AI (passed validation)",
  HUMAN_ACCEPTED: "Human accepted",
  HUMAN_EDITED: "Human edited",
  HUMAN_REJECTED: "Human rejected",
  INTAKE: "Intake form",
  WARRANTY_REGISTRY: "Warranty registry",
};

/** Band a confidence score against the routing threshold. */
export function confidenceBand(score, threshold = 80) {
  if (score === null || score === undefined) return "none";
  if (score >= threshold) return "high";
  if (score >= threshold - 20) return "medium";
  return "low";
}

export function humanize(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value).replaceAll("_", " ");
}

export function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

/** Which pipeline stage is the claim at, and how did each stage end? */
export function pipelineStages(claim, threshold = 80) {
  const analyzed = !!claim?.aiAnalysis;
  const failed = claim?.validation?.failedRules || [];
  const lowConf = analyzed && claim.aiConfidence < threshold;
  const final = ["APPROVED", "ESCALATED"].includes(claim?.validationStatus);
  return [
    { key: "ai", label: "AI Prediction", state: analyzed ? "done" : "active",
      note: analyzed ? claim.aiProvider : "waiting" },
    { key: "conf", label: "Confidence", state: !analyzed ? "idle" : lowConf ? "warn" : "done",
      note: analyzed ? `${claim.aiConfidence}% (threshold ${threshold}%)` : "—" },
    { key: "val", label: "Business Validation", state: !analyzed ? "idle" : failed.length ? "warn" : "done",
      note: analyzed ? (failed.length ? `${failed.length} rule(s) failed` : "all rules passed") : "—" },
    { key: "final", label: "Final Status", state: final ? (claim.validationStatus === "APPROVED" ? "done" : "bad") : analyzed ? "active" : "idle",
      note: STATUS_META[claim?.validationStatus]?.label || "—" },
  ];
}
