"""
Rule-based NLP extraction engine ("Rule-based AI simulation" option in the brief).

Deterministic, explainable, no API key. Every field returns:
    {"value": ..., "confidence": 0-100, "evidence": "why"}

Confidence is built from evidence strength, not hard-coded per field:
    explicit statement in text   -> high  (85-95)
    inferred from symptom->part  -> mid   (50-70)
    nothing found                -> low / null
and penalised when the text contradicts itself (e.g. part already replaced but
symptom persists -> that part being the root cause is uncertain).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- knowledge base

PARTS: dict[str, list[str]] = {
    "Power Module": ["power module", "power supply", "psu", "power adapter", "power unit", "power board"],
    "Battery": ["battery", "batteries"],
    "Antenna": ["antenna", "antennas"],
    "Network Port": ["ethernet port", "network port", "lan port", "wan port", "rj45", "rj-45"],
    "Wi-Fi Radio": ["wifi module", "wi-fi module", "wireless module", "radio module", "wifi card", "wireless card"],
    "Mainboard": ["motherboard", "mainboard", "main board", "logic board", "circuit board", "pcb", "controller board"],
    "Firmware": ["firmware"],
    "Cooling Fan": ["cooling fan", "fan"],
    "Display": ["display", "screen", "lcd", "touchscreen", "touch screen"],
    "Storage Drive": ["hard drive", "hdd", "ssd", "disk drive"],
    "Compressor": ["compressor"],
    "Motor": ["motor"],
    "Pump": ["pump"],
    "Bearing": ["bearing", "bearings"],
    "Valve": ["valve"],
    "Sensor": ["sensor", "thermostat"],
    "Cable/Connector": ["cable", "connector", "wiring", "harness"],
    "Control Panel": ["control panel", "keypad", "button panel"],
}

HARDWARE_PARTS = set(PARTS) - {"Firmware"}


@dataclass
class Symptom:
    name: str
    patterns: list[str]
    category: str
    severity: str
    likely_parts: list[str] = field(default_factory=list)


SYMPTOMS: list[Symptom] = [
    Symptom("Safety hazard (smoke/sparks/burning)",
            [r"\bsmok(e|ing)\b", r"\bspark(s|ing)?\b", r"burning smell", r"\bfire\b", r"electric(al)? shock", r"\bmelt(ed|ing)\b"],
            "Safety Hazard", "CRITICAL", ["Power Module", "Cable/Connector"]),
    Symptom("Intermittent connectivity",
            [r"intermittent(ly)? (connectivity|connection|network|signal|link)", r"connection (keeps )?drop", r"drops? (the )?connection",
             r"keeps disconnecting", r"loses? (connection|connectivity|signal)", r"(connectivity|connection) (is )?intermittent"],
            "Connectivity/Network", "MEDIUM", ["Wi-Fi Radio", "Antenna", "Network Port"]),
    Symptom("No connectivity",
            [r"no (internet|connectivity|network|signal)", r"cannot connect", r"can't connect", r"unable to connect"],
            "Connectivity/Network", "HIGH", ["Network Port", "Wi-Fi Radio"]),
    Symptom("Device does not power on",
            [r"no power", r"won'?t (turn|power) on", r"will not (turn|power) on", r"does ?n[o']t (turn|power) on", r"not powering",
             r"\bdead\b", r"fails? to (boot|start|power)"],
            "Power/Electrical", "HIGH", ["Power Module", "Battery", "Mainboard"]),
    Symptom("Overheating",
            [r"overheat", r"running hot", r"too hot", r"thermal shutdown", r"excessive heat"],
            "Overheating/Thermal", "HIGH", ["Cooling Fan", "Sensor"]),
    Symptom("Not cooling",
            [r"not cooling", r"insufficient cooling", r"blow(s|ing)? warm air", r"no cooling"],
            "Mechanical Wear", "HIGH", ["Compressor", "Sensor"]),
    Symptom("Unexpected reboots",
            [r"reboot", r"restart(s|ing)?", r"boot ?loop", r"power cycles?"],
            "Software/Firmware", "MEDIUM", ["Firmware", "Power Module"]),
    Symptom("Abnormal noise / vibration",
            [r"grinding", r"rattl", r"squeal", r"\bnois(e|y)\b", r"vibrat"],
            "Mechanical Wear", "MEDIUM", ["Bearing", "Motor", "Cooling Fan"]),
    Symptom("Leak",
            [r"\bleak", r"dripping"],
            "Mechanical Wear", "HIGH", ["Valve", "Pump"]),
    Symptom("Display malfunction",
            [r"flicker", r"blank screen", r"no display", r"dead pixels?", r"screen (is )?(black|blank)"],
            "Hardware Failure", "MEDIUM", ["Display"]),
    Symptom("Error code reported",
            [r"error code", r"\berror [A-Z]?\d+", r"fault code"],
            "Software/Firmware", "MEDIUM", ["Firmware"]),
    Symptom("Physical damage",
            [r"crack(ed)?", r"\bbroken\b", r"\bdropped\b", r"water damage", r"\bdent(ed)?\b", r"liquid spill"],
            "Physical Damage", "MEDIUM", []),
    Symptom("Slow / degraded performance",
            [r"\bslow\b", r"\blag(gy|s)?\b", r"sluggish", r"degraded performance"],
            "Software/Firmware", "LOW", ["Firmware"]),
    Symptom("Installation / configuration issue",
            [r"misconfigur", r"cannot configure", r"installation (issue|problem|error)", r"setup (issue|problem|fails?)"],
            "Installation/Configuration", "LOW", []),
]

SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RECURRENCE = [r"\btwice\b", r"\bagain\b", r"\bstill\b", r"repeated(ly)?", r"multiple times", r"recurring", r"keeps", r"three times"]
BUSINESS_IMPACT = [r"production (is )?down", r"all users", r"\boutage\b", r"line stopped", r"business[- ]critical"]

CAUSE_STATEMENT = re.compile(
    r"\b(technician|tech|engineer|field engineer|support)\s+(suspects|believes|thinks|suspected|diagnosed|confirmed|found|identified)\s+"
    r"(?:that\s+)?(?:a |an |the )?([^.;\n]+)", re.I)
CAUSED_BY = re.compile(r"\b(caused by|due to|because of|result of)\s+(?:a |an |the )?([^.;\n]+)", re.I)
REPEAT_WORDS = r"(twice|two times|three times|\d+ times|again|multiple times|several times)"

MODEL_RE = re.compile(r"\b(?!SN)([A-Z]{1,4})[- ]?(\d{2,5})([A-Z]{0,2})\b")
SERIAL_RE = [
    re.compile(r"\bserial(?:\s*(?:no\.?|number|#))?\s*(?:is|:|#)?\s*([A-Z0-9][A-Z0-9-]{4,})", re.I),
    re.compile(r"\b(SN[-:]?\s?[A-Z0-9]{4,})\b"),
]
UNDER_WARRANTY_RE = re.compile(r"\b(under|in|within) warranty\b|\bwarranty (is )?(valid|active)\b|covered by (the )?warranty", re.I)
EXPIRED_RE = re.compile(r"\b(out of|no longer under|not under|not in|outside( of)?) warranty\b|warranty (has )?expired|expired warranty", re.I)


def normalize_model(value: str | None) -> str | None:
    if not value:
        return None
    m = MODEL_RE.search(value.upper())
    if not m:
        return value.strip().upper()
    return f"{m.group(1)}-{m.group(2)}{m.group(3)}"


def normalize_serial(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[\s:-]", "", value.strip().upper())


def _f(value, confidence: int, evidence: str) -> dict:
    return {"value": value, "confidence": max(0, min(100, int(confidence))), "evidence": evidence}


def _find_parts(text: str) -> list[str]:
    low = text.lower()
    found: list[tuple[int, str]] = []
    for part, aliases in PARTS.items():
        for alias in aliases:
            m = re.search(rf"\b{re.escape(alias)}\b", low)
            if m:
                found.append((m.start(), part))
                break
    found.sort()
    return [p for _, p in found]


def _part_in(text: str) -> str | None:
    parts = _find_parts(text)
    return parts[0] if parts else None


# --------------------------------------------------------------------------- field extractors

def extract_model(text: str, form_model: str | None) -> dict:
    m = MODEL_RE.search(text)
    text_model = f"{m.group(1)}-{m.group(2)}{m.group(3)}" if m else None
    form_norm = normalize_model(form_model)
    if text_model and form_norm:
        if text_model == form_norm:
            return _f(form_norm, 98, f"'{m.group(0)}' in description matches intake model")
        return _f(text_model, 55, f"description mentions '{m.group(0)}' but intake says '{form_model}'")
    if text_model:
        return _f(text_model, 85, f"'{m.group(0)}' found in description")
    if form_norm:
        return _f(form_norm, 92, "not in description; taken from intake form")
    return _f(None, 0, "no model found")


def extract_serial(text: str, form_serial: str | None) -> dict:
    text_serial = None
    for rx in SERIAL_RE:
        m = rx.search(text)
        if m:
            text_serial = normalize_serial(m.group(1))
            break
    form_norm = normalize_serial(form_serial)
    if text_serial and form_norm:
        if text_serial == form_norm:
            return _f(form_norm, 99, "serial in description matches intake")
        return _f(text_serial, 50, f"description serial '{text_serial}' != intake '{form_norm}'")
    if text_serial:
        return _f(text_serial, 85, "serial found in description")
    if form_norm:
        return _f(form_norm, 97, "not in description; taken from intake form")
    return _f(None, 0, "no serial number in claim")


def extract_symptoms(text: str) -> list[Symptom]:
    low = text.lower()
    return [s for s in SYMPTOMS if any(re.search(p, low) for p in s.patterns)]


def extract_warranty(text: str, form_status: str | None) -> dict:
    if EXPIRED_RE.search(text):
        return _f("EXPIRED", 90, "description states warranty expired")
    if UNDER_WARRANTY_RE.search(text):
        return _f("UNDER_WARRANTY", 90, "description states device is under warranty")
    if form_status in ("UNDER_WARRANTY", "EXPIRED"):
        return _f(form_status, 70, "not in description; taken from intake form")
    return _f("UNKNOWN", 40, "warranty not mentioned")


def analyze(description: str, form_model: str | None = None, form_serial: str | None = None,
            form_warranty: str | None = None) -> dict:
    text = description.strip()
    low = text.lower()
    symptoms = extract_symptoms(text)
    parts_mentioned = _find_parts(text)
    recurring = any(re.search(p, low) for p in RECURRENCE)
    impact = any(re.search(p, low) for p in BUSINESS_IMPACT)

    # ---- replaced parts: a part replaced and symptom persisting weakens it as root cause
    replaced_parts: dict[str, str] = {}
    for part, aliases in PARTS.items():
        for alias in aliases:
            m = re.search(rf"\b(?:replaced|swapped|changed) (?:the |a |an )?{re.escape(alias)}\b(?:\s+{REPEAT_WORDS})?", low)
            if m:
                replaced_parts[part] = m.group(1) or "once"
                break
    repeat_replaced = any(v != "once" for v in replaced_parts.values())
    persists = repeat_replaced or bool(re.search(
        r"\bstill\b(?! (under|in|within|covered))|persists|continues|not (fixed|resolved)|did ?n[o']t (fix|help|resolve)", low))

    # ---- symptom
    if symptoms:
        primary = symptoms[0]
        conf = 90 if len(symptoms) == 1 else 82
        symptom = _f(primary.name if len(symptoms) == 1 else f"{primary.name}; " + "; ".join(s.name for s in symptoms[1:]),
                     conf, "matched: " + ", ".join(s.name for s in symptoms))
    else:
        primary = None
        first_sentence = re.split(r"(?<=[.!?])\s", text)[0][:160]
        symptom = _f(first_sentence, 45, "no known symptom pattern; first sentence used")

    # ---- suspected cause
    cause_val, cause_conf, cause_ev, cause_part = None, 0, "no cause stated or inferable", None
    stmt = CAUSE_STATEMENT.search(text)
    by = CAUSED_BY.search(text)
    if stmt:
        verb, phrase = stmt.group(2).lower(), stmt.group(3).strip().rstrip(".")
        firm = verb in {"diagnosed", "confirmed", "found", "identified"}
        stated_part = _part_in(phrase)
        if stated_part:
            cause_part = stated_part
            cause_val = f"{stated_part} failure"
            cause_conf = 92 if firm else 78
        else:
            # generic statement ("hardware failure") -> pin it to the part the text talks about
            cause_part = next((p for p in parts_mentioned if p in HARDWARE_PARTS), None)
            cause_val = f"{cause_part} failure" if cause_part else phrase[:1].upper() + phrase[1:]
            cause_conf = (80 if firm else 70) if cause_part else (70 if firm else 55)
        cause_ev = f"{stmt.group(1)} {verb}: '{phrase}'"
    elif by:
        phrase = by.group(2).strip().rstrip(".")
        cause_part = _part_in(phrase)
        cause_val = f"{cause_part} failure" if cause_part else phrase[:1].upper() + phrase[1:]
        cause_conf = 82
        cause_ev = f"'{by.group(1)} {phrase}'"
    elif primary:
        candidates = [p for p in primary.likely_parts if p in parts_mentioned] or primary.likely_parts
        if candidates:
            cause_part = candidates[0]
            cause_val = f"{cause_part} failure"
            cause_conf = 62 if cause_part in parts_mentioned else 48
            cause_ev = f"inferred from symptom '{primary.name}'"
    if cause_part and cause_part in replaced_parts and persists:
        cause_conf -= 10
        cause_ev += f"; NOTE {cause_part} already replaced ({replaced_parts[cause_part]}) and issue persists"
    suspected_cause = _f(cause_val, cause_conf, cause_ev)

    # ---- affected part
    if cause_part:
        affected = _f(cause_part, min(90, cause_conf + 12) if cause_part in parts_mentioned else cause_conf,
                      "part named in text" if cause_part in parts_mentioned else "inferred from symptom")
    elif parts_mentioned:
        affected = _f(parts_mentioned[0], 70, "first part mentioned in text")
    else:
        affected = _f(None, 0, "no part identified")

    # ---- category
    if stmt and re.search(r"hardware (failure|fault|issue|defect)", stmt.group(3), re.I):
        category = _f("Hardware Failure", 91, "technician statement says hardware failure")
    elif primary and primary.category == "Safety Hazard":
        category = _f("Safety Hazard", 95, "safety keywords present")
    elif cause_part and cause_part in HARDWARE_PARTS and cause_conf >= 70:
        category = _f("Hardware Failure", 85, f"cause attributed to hardware part '{cause_part}'")
    elif symptoms:
        cats = {s.category for s in symptoms}
        category = _f(primary.category, 86 if len(cats) == 1 else 68,
                      "from symptom" + ("" if len(cats) == 1 else f"; competing categories {sorted(cats)}"))
    else:
        category = _f("Other", 40, "no category signal")

    # ---- severity
    if primary and primary.severity == "CRITICAL":
        severity = _f("CRITICAL", 95, "safety hazard keywords")
    elif symptoms:
        base = max(SEVERITY_ORDER.index(s.severity) for s in symptoms)
        reasons = [f"base {SEVERITY_ORDER[base]} from symptom"]
        if recurring:
            base, reasons = min(base + 1, 2), reasons + ["recurring issue"]
        if impact:
            base, reasons = min(base + 1, 2), reasons + ["business impact stated"]
        if stmt and stmt.group(2).lower() in {"diagnosed", "confirmed", "found", "identified"}:
            reasons.append("diagnosis confirmed by technician")
        conf = (80 if len(symptoms) == 1 else 70) + 6 * (len(reasons) - 1)
        severity = _f(SEVERITY_ORDER[base], min(conf, 92), "; ".join(reasons))
    else:
        severity = _f("MEDIUM", 45, "no severity signal; default")

    # ---- resolution
    if primary and primary.severity == "CRITICAL":
        resolution = _f("Isolate unit from power immediately; safety inspection by certified technician before any repair",
                        92, "safety protocol")
    elif cause_part == "Firmware":
        resolution = _f("Update firmware to latest release and factory-reset configuration", max(cause_conf, 60), "firmware cause")
    elif cause_part and cause_part in replaced_parts and persists:
        resolution = _f(f"Run full diagnostics; {cause_part} already replaced ({replaced_parts[cause_part]}) without fix - "
                        f"inspect upstream components (mainboard/cabling) before replacing {cause_part} again",
                        max(cause_conf - 5, 40), "repeat replacement did not resolve symptom")
    elif cause_part:
        resolution = _f(f"Inspect and replace {cause_part}", min(cause_conf + 5, 92), f"standard fix for {cause_part} failure")
    elif primary and primary.category == "Installation/Configuration":
        resolution = _f("Remote configuration review and guided re-installation", 70, "configuration category")
    elif primary and primary.category == "Physical Damage":
        resolution = _f("Assess damage on-site; physical damage is typically not covered by warranty", 72, "physical damage")
    else:
        resolution = _f("Remote diagnostics required before dispatch", 40, "insufficient information")

    return {
        "equipmentModel": extract_model(text, form_model),
        "serialNumber": extract_serial(text, form_serial),
        "category": category,
        "symptom": symptom,
        "suspectedCause": suspected_cause,
        "affectedPart": affected,
        "severity": severity,
        "resolution": resolution,
        "warrantyRelevance": extract_warranty(text, form_warranty),
    }
