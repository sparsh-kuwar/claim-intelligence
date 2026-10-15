"""
Load docs/samples/sample_claims.json through the public API (submit + analyze),
then write the AI output of each to docs/samples/sample_ai_output.json.

    python scripts/load_samples.py [--api http://localhost:8000]
"""
import argparse
import json
import pathlib

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "docs" / "samples" / "sample_claims.json"
OUT = ROOT / "docs" / "samples" / "sample_ai_output.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    args = p.parse_args()
    out = []
    with httpx.Client(base_url=args.api, timeout=60) as c:
        for claim in json.loads(SAMPLES.read_text()):
            scenario = claim.pop("_scenario", "")
            r = c.post("/api/claims", json=claim)
            r.raise_for_status()
            cid = r.json()["claimId"]
            d = c.post(f"/api/claims/{cid}/analyze").json()
            print(f"{cid}  {d['validationStatus']:<20} conf={d['aiConfidence']:>3}%  failed={d['validation']['failedRules']}  | {scenario}")
            out.append({"scenario": scenario, "claimId": cid, "input": claim, "aiProvider": d["aiProvider"],
                        "overallConfidence": d["aiConfidence"], "aiAnalysis": d["aiAnalysis"],
                        "validation": {k: d["validation"][k] for k in
                                       ("threshold", "outcome", "failedRules", "flaggedFields", "fieldsRequiringReview",
                                        "registryWarrantyStatus", "rules")},
                        "routedStatus": d["validationStatus"]})
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
