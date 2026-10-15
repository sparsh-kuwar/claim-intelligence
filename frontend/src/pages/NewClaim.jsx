import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";
import { formatDateTime } from "../lib/format.js";
import { ErrorBox, StatusBadge } from "../components/ui.jsx";

const EMPTY = { customer: "", equipmentModel: "", serialNumber: "", description: "", serviceDate: "", warrantyStatus: "" };

const EXAMPLES = [
  { label: "PDF example (low confidence)", data: { customer: "ABC Manufacturing", equipmentModel: "AX-500", serialNumber: "SN10231",
    description: "Router AX500 has intermittent connectivity. Customer replaced the power module twice. Device is still under warranty. Technician suspects a hardware failure.",
    serviceDate: "2026-09-20", warrantyStatus: "UNDER_WARRANTY" } },
  { label: "Clean claim", data: { customer: "Delta Foods", equipmentModel: "CH-900", serialNumber: "SN77310",
    description: "Chiller CH-900 serial SN77310 is not cooling since Monday. Technician confirmed compressor failure after inspection. Unit is under warranty.",
    serviceDate: "2026-09-18", warrantyStatus: "UNDER_WARRANTY" } },
  { label: "Safety hazard", data: { customer: "Metro Print Co", equipmentModel: "LX-220", serialNumber: "SN55501",
    description: "Printer LX-220 serial SN55501 started smoking and there is a burning smell from the rear power supply area.",
    serviceDate: "2026-09-21", warrantyStatus: "UNDER_WARRANTY" } },
  { label: "Warranty conflict", data: { customer: "Orbit Logistics", equipmentModel: "AX-500", serialNumber: "SN10232",
    description: "Router AX-500 does not power on. Technician confirmed power module failure. Customer says unit is under warranty.",
    serviceDate: "2026-09-12", warrantyStatus: "UNDER_WARRANTY" } },
  { label: "Missing serial", data: { customer: "Sunrise Hotels", equipmentModel: "PX-150", serialNumber: "",
    description: "Display on the PX-150 kiosk keeps flickering and sometimes the screen goes blank. Technician suspects display failure.",
    serviceDate: "2026-09-15", warrantyStatus: "UNKNOWN" } },
];

function clientValidate(f) {
  const e = {};
  if (f.customer.trim().length < 2) e.customer = "Customer name is required";
  if (!f.equipmentModel.trim()) e.equipmentModel = "Equipment model is required";
  if (f.description.trim().length < 10) e.description = "Describe the issue (min 10 characters)";
  if (!f.serviceDate) e.serviceDate = "Service date is required";
  else if (f.serviceDate > new Date().toISOString().slice(0, 10)) e.serviceDate = "Service date cannot be in the future";
  if (!f.warrantyStatus) e.warrantyStatus = "Select warranty status";
  return e;
}

export default function NewClaim() {
  const [form, setForm] = useState(EMPTY);
  const [file, setFile] = useState(null);
  const [errors, setErrors] = useState({});
  const [apiError, setApiError] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    const v = clientValidate(form);
    setErrors(v);
    if (Object.keys(v).length) return;
    setBusy(true); setApiError(null); setReceipt(null); setResult(null);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, val]) => fd.append(k, val));
      if (file) fd.append("attachment", file);
      const r = await api.create(fd);
      setReceipt(r);                                  // Claim ID + timestamp + PROCESSING
      const analyzed = await api.analyze(r.claimId);  // AI + validation
      setResult(analyzed);
      setReceipt({ ...r, status: analyzed.validationStatus });
    } catch (err) {
      setApiError(err);
    } finally {
      setBusy(false);
    }
  }

  function reset() { setForm(EMPTY); setFile(null); setReceipt(null); setResult(null); setErrors({}); }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Submit Service Claim</h1>
          <p className="muted">The claim is stored first, then analyzed by the AI service and checked by business rules.</p>
        </div>
      </div>

      <div className="grid-2">
        <form className="card form" onSubmit={submit} noValidate data-testid="claim-form">
          <div className="examples">
            <span className="muted small">Load sample:</span>
            {EXAMPLES.map((x) => (
              <button type="button" key={x.label} className="chip" onClick={() => { setForm(x.data); setErrors({}); }}>{x.label}</button>
            ))}
          </div>

          <Field label="Customer name" error={errors.customer}>
            <input className="input" name="customer" value={form.customer} onChange={set("customer")} maxLength={200} />
          </Field>
          <div className="row-2">
            <Field label="Equipment model" error={errors.equipmentModel}>
              <input className="input" name="equipmentModel" value={form.equipmentModel} onChange={set("equipmentModel")} placeholder="AX-500" maxLength={100} />
            </Field>
            <Field label="Serial number" hint="Optional, but missing serial forces human review">
              <input className="input" name="serialNumber" value={form.serialNumber} onChange={set("serialNumber")} placeholder="SN10231" maxLength={100} />
            </Field>
          </div>
          <Field label="Claim description" error={errors.description}>
            <textarea className="input" name="description" rows={5} value={form.description} onChange={set("description")} maxLength={5000}
                      placeholder="What happened, what was tried, what the technician suspects…" />
          </Field>
          <div className="row-2">
            <Field label="Service date" error={errors.serviceDate}>
              <input className="input" type="date" name="serviceDate" value={form.serviceDate} onChange={set("serviceDate")} />
            </Field>
            <Field label="Warranty status (as claimed)" error={errors.warrantyStatus}>
              <select className="input" name="warrantyStatus" value={form.warrantyStatus} onChange={set("warrantyStatus")}>
                <option value="">Select…</option>
                <option value="UNDER_WARRANTY">Under warranty</option>
                <option value="EXPIRED">Expired</option>
                <option value="UNKNOWN">Unknown</option>
              </select>
            </Field>
          </div>
          <Field label="Attachment (optional)" hint="PDF, PNG, JPG, TXT, LOG, CSV · max 5 MB">
            <input className="input" type="file" name="attachment" accept=".pdf,.png,.jpg,.jpeg,.txt,.log,.csv"
                   onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </Field>

          <ErrorBox error={apiError} />
          <div className="actions">
            <button className="btn btn-primary" disabled={busy} type="submit">{busy ? "Submitting…" : "Submit claim"}</button>
            <button className="btn" type="button" onClick={reset}>Clear</button>
          </div>
        </form>

        <div>
          {!receipt && (
            <div className="card placeholder">
              <h3>What happens after you submit</h3>
              <ol className="steps">
                <li><b>Stored</b> with a Claim ID and status PROCESSING</li>
                <li><b>AI prediction</b> extracts model, serial, symptom, cause, part, severity, resolution, warranty, category — each with a confidence score</li>
                <li><b>Business validation</b> runs rules R1–R6 (missing serial, low confidence, warranty conflict vs registry, critical severity, required fields, identity mismatch)</li>
                <li><b>Routing</b>: all rules pass → Ready for Approval; anything fails → Human Review</li>
              </ol>
            </div>
          )}
          {receipt && (
            <div className="card receipt" data-testid="receipt">
              <div className="receipt-head">Claim received</div>
              <dl className="kv">
                <dt>Claim ID</dt><dd className="mono strong" data-testid="receipt-id">{receipt.claimId}</dd>
                <dt>Submitted</dt><dd>{formatDateTime(receipt.submittedAt)}</dd>
                <dt>Customer</dt><dd>{receipt.customer}</dd>
                <dt>Model</dt><dd>{receipt.equipmentModel}</dd>
                <dt>Serial</dt><dd className="mono">{receipt.serialNumber || "—"}</dd>
                <dt>Status</dt><dd><StatusBadge status={receipt.status} /></dd>
              </dl>
              {result && (
                <>
                  <div className={`alert ${result.validationStatus === "NEEDS_REVIEW" ? "alert-warn" : "alert-ok"}`}>
                    {result.validationStatus === "NEEDS_REVIEW"
                      ? `Routed to human review — failed rules: ${result.validation.failedRules.join(", ")}`
                      : "All validation rules passed — eligible for approval."}
                    <div className="small">Overall AI confidence: <b>{result.aiConfidence}%</b></div>
                  </div>
                  <Link className="btn btn-primary" to={`/claims/${receipt.claimId}`} data-testid="open-claim">Open claim →</Link>
                </>
              )}
              {!result && busy && <p className="muted">Running AI analysis…</p>}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Field({ label, error, hint, children }) {
  return (
    <label className={`field ${error ? "field-error" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {error ? <span className="field-msg">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}
