import { describe, expect, it } from "vitest";
import { confidenceBand, humanize, pipelineStages } from "./format.js";

describe("confidenceBand", () => {
  it("bands against the threshold", () => {
    expect(confidenceBand(91, 80)).toBe("high");
    expect(confidenceBand(80, 80)).toBe("high");
    expect(confidenceBand(68, 80)).toBe("medium");
    expect(confidenceBand(40, 80)).toBe("low");
    expect(confidenceBand(null, 80)).toBe("none");
  });
});

describe("humanize", () => {
  it("replaces underscores and handles empties", () => {
    expect(humanize("UNDER_WARRANTY")).toBe("UNDER WARRANTY");
    expect(humanize(null)).toBe("—");
  });
});

describe("pipelineStages", () => {
  it("marks low confidence and failed validation as warnings", () => {
    const claim = { aiAnalysis: {}, aiProvider: "rule_based", aiConfidence: 60,
      validation: { failedRules: ["R2"] }, validationStatus: "NEEDS_REVIEW" };
    const s = pipelineStages(claim, 80);
    expect(s.map((x) => x.state)).toEqual(["done", "warn", "warn", "active"]);
  });
  it("shows a clean approved claim as all done", () => {
    const claim = { aiAnalysis: {}, aiConfidence: 90, validation: { failedRules: [] }, validationStatus: "APPROVED" };
    expect(pipelineStages(claim, 80).every((x) => x.state === "done")).toBe(true);
  });
});
