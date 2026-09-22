"""Pure grading logic. No network, no files, no clock.

Everything here is deterministic: same input, same output, always.
"""

import re
import unicodedata

DIMENSIONS = ["point", "mechanism", "evidence", "impact"]

# Highest threshold first. Calibrated against 42 real submissions, 2026-09-19.
LABELS = [
    (11, "Strong"),
    (9, "Solid"),
    (7, "Developing"),
    (4, "Foundations"),
]

# Only these come from the model. The rest are computed from the scores.
JUDGED_FLAGS = [
    "unverified_factual_claim",
    "clustered_arguments",
    "rhetoric_without_work",
    "off_topic",
    "wrong_side",
]

REQUIRED_FIELDS = [
    "sufficient", "scores", "anchor_evidence", "weighing_attempted",
    "strongest_moment", "biggest_gap", "one_fix", "rewrite_example",
    "flags", "confidence",
]

DEFAULTS = {
    "sufficient": False,
    "insufficient_reason": "",
    "scores": {},
    "anchor_evidence": {},
    "weighing_attempted": False,
    "strongest_moment": {"quote": "", "why": ""},
    "biggest_gap": "",
    "one_fix": "",
    "rewrite_example": {"original": "", "improved": ""},
    "flags": [],
    "confidence": "low",
}

# Fields that must quote the submission verbatim.
QUOTE_FIELDS = [("strongest_moment", "quote"), ("rewrite_example", "original")]

GRADE_TOOL = {
    "name": "record_grade",
    "description": "Record the structured evaluation of one debate drill submission.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sufficient": {"type": "boolean"},
            "insufficient_reason": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {
                    d: {"type": "integer", "minimum": 0, "maximum": 5}
                    for d in DIMENSIONS
                },
                "required": DIMENSIONS,
            },
            "anchor_evidence": {
                "type": "object",
                "properties": {d: {"type": "string"} for d in DIMENSIONS},
                "required": DIMENSIONS,
            },
            "weighing_attempted": {"type": "boolean"},
            "strongest_moment": {
                "type": "object",
                "properties": {"quote": {"type": "string"}, "why": {"type": "string"}},
                "required": ["quote", "why"],
            },
            "biggest_gap": {"type": "string"},
            "one_fix": {"type": "string"},
            "rewrite_example": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "improved": {"type": "string"},
                },
                "required": ["original", "improved"],
            },
            "flags": {"type": "array", "items": {"type": "string", "enum": JUDGED_FLAGS}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": REQUIRED_FIELDS,
    },
}

_PUNCT_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ",
})


def canon(text):
    """Fold unicode, punctuation and whitespace so 'verbatim' is checkable.

    Quote characters are dropped entirely: debaters type curly apostrophes,
    exports mangle them into double quotes, and the model straightens them.
    None of that changes what the sentence says.
    """
    text = unicodedata.normalize("NFKC", str(text))
    text = text.translate(_PUNCT_MAP)
    text = re.sub(r"['\"]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def normalise(grade):
    """The schema guides the model; it does not guarantee. Defend here.

    Fills missing fields, coerces score types, demotes unusable grades.
    Mutates grade in place. Returns a list of problems.
    """
    problems = [f"missing field {k!r}" for k in REQUIRED_FIELDS if k not in grade]

    for key, default in DEFAULTS.items():
        grade.setdefault(key, default)

    for d in DIMENSIONS:
        raw = grade["scores"].get(d)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            problems.append(f"scores.{d} = {raw!r} is not a number")
            value = 0
        grade["scores"][d] = value

        if grade["sufficient"] and not 1 <= value <= 5:
            problems.append(f"scores.{d} = {value} outside 1-5 while sufficient")
            grade["sufficient"] = False
            grade["insufficient_reason"] = "malformed scores"

    return problems


def derive_flags(grade, submission_text):
    """Flags with arithmetic definitions belong in code, not in a prompt."""
    flags = []
    words = len(submission_text.split())

    if words < 40:
        flags.append("too_short")
    elif words < 60:
        flags.append("thin_submission")

    if grade["sufficient"]:
        scores = grade["scores"]
        if scores["point"] == 1:
            flags.append("no_position")
        if scores["mechanism"] == 1:
            flags.append("assertion_only")
        if scores["evidence"] == 2:
            flags.append("name_drop_evidence")

    return flags


def score_grade(grade, submission_text):
    """Compute total, label and derived flags. The model never counts."""
    derived = derive_flags(grade, submission_text)
    all_flags = sorted(set(grade.get("flags", [])) | set(derived))

    if not grade["sufficient"]:
        return {"total": None, "label": None, "flags": all_flags}

    total = sum(grade["scores"][d] for d in DIMENSIONS)

    label = "Foundations"
    for threshold, name in LABELS:
        if total >= threshold:
            label = name
            break

    if grade["scores"]["point"] == 1 or grade["scores"]["mechanism"] == 1:
        label = "Foundations"

    return {"total": total, "label": label, "flags": all_flags}


def bad_quotes(grade, submission_text):
    """Return the quote fields that are not verbatim from the submission."""
    haystack = canon(submission_text)
    bad = []
    for section, key in QUOTE_FIELDS:
        value = grade.get(section, {}).get(key, "")
        if value and canon(value) not in haystack:
            bad.append((section, key))
    return bad


def strip_bad_quotes(grade, submission_text):
    """Remove unverifiable quotes rather than show a debater words they never wrote."""
    removed = []
    for section, key in bad_quotes(grade, submission_text):
        grade[section][key] = ""
        if section == "rewrite_example":
            grade[section]["improved"] = ""
        removed.append(f"{section}.{key}")
    return removed


def validate(grade, submission_text):
    """Checks the schema and normalise cannot make. Returns problems."""
    problems = []

    if not grade["sufficient"]:
        if not str(grade["insufficient_reason"]).strip():
            problems.append("sufficient is false but no reason given")
        return problems

    for field, cap in [("biggest_gap", 30), ("one_fix", 45)]:
        n = len(str(grade[field]).split())
        if n > cap:
            problems.append(f"{field} is {n} words, cap is {cap}")

    for section, key in bad_quotes(grade, submission_text):
        value = grade[section][key]
        problems.append(f"{section}.{key} is not verbatim: {value[:50]!r}")

    return problems


def build_user_message(submission_text, motion=None, side=None):
    """Only include fields that are present - absent fields are omitted."""
    lines = []
    if motion:
        lines.append(f"motion: {motion}")
    if side:
        lines.append(f"side: {side}")
    lines.append(f"submission:\n{submission_text}")
    return "\n".join(lines)

FALLBACK_REASONS = {
    "too_short": "This is under 40 words - too short to evaluate. Aim for at least 60.",
    "off_topic": "This does not address the motion you were given.",
    "wrong_side": "This argues the opposite side to the one you were assigned.",
}

GENERIC_REASON = (
    "This did not read as an attempt at the drill - it needs a position you are "
    "defending, not a description of the topic."
)


def ensure_reason(grade, submission_text):
    """A rejected submission must always tell the debater why."""
    if grade["sufficient"] or str(grade["insufficient_reason"]).strip():
        return False

    for flag in derive_flags(grade, submission_text) + grade.get("flags", []):
        if flag in FALLBACK_REASONS:
            grade["insufficient_reason"] = FALLBACK_REASONS[flag]
            return True

    grade["insufficient_reason"] = GENERIC_REASON
    return True