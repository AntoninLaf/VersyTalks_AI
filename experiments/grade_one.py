import re
import unicodedata

_PUNCT_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ",
})


def canon(text):
    """Collapse unicode, quote style and whitespace so 'verbatim' is checkable."""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.translate(_PUNCT_MAP)
    return re.sub(r"\s+", " ", text).strip().lower()

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000

PROMPT_PATH = Path("prompts/argument_classic_v1.md")
SAMPLES_PATH = Path("experiments/samples.json")

DIMENSIONS = ["point", "mechanism", "evidence", "impact"]

# Highest threshold first - the first match wins.
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
def derive_flags(grade, submission_text):
    """Flags whose definition is arithmetic belong in code, not in a prompt."""
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
                "properties": {
                    "quote": {"type": "string"},
                    "why": {"type": "string"},
                },
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
            "flags": {
                "type": "array",
                "items": {"type": "string", "enum": JUDGED_FLAGS},
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": [
            "sufficient", "insufficient_reason", "scores", "anchor_evidence",
            "weighing_attempted", "strongest_moment", "biggest_gap",
            "one_fix", "rewrite_example", "flags", "confidence",
        ],
    },
}

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


def normalise(grade):
    """The schema guides the model; it does not guarantee. Defend here.

    Fills missing fields, coerces score types, and demotes a grade to
    insufficient if its scores are unusable. Returns a list of problems.
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

def score_grade(grade, submission_text):
    """Compute total, label and derived flags in code."""
    derived = derive_flags(grade, submission_text)
    all_flags = sorted(set(grade["flags"]) | set(derived))

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

    # Floor override: no position or no reason caps the label.
    if grade["scores"]["point"] == 1 or grade["scores"]["mechanism"] == 1:
        label = "Foundations"

    return {"total": total, "label": label}


def validate(grade, submission_text):
    """Checks the schema cannot make. Returns a list of problems."""
    problems = []
    scores = grade["scores"]

    if not grade["sufficient"]:
        if any(scores[d] != 0 for d in DIMENSIONS):
            problems.append("sufficient is false but scores are not all 0")
        if not grade["insufficient_reason"].strip():
            problems.append("sufficient is false but no reason given")
        return problems

    for d in DIMENSIONS:
        if not 1 <= scores[d] <= 5:
            problems.append(f"scores.{d} = {scores[d]}, expected 1-5")

    for field, cap in [("biggest_gap", 30), ("one_fix", 45)]:
        n = len(grade[field].split())
        if n > cap:
            problems.append(f"{field} is {n} words, cap is {cap}")

        for section, key in [("strongest_moment", "quote"), ("rewrite_example", "original")]:
            value = grade[section][key]
            if value and canon(value) not in canon(submission_text):
                problems.append(f"{section}.{key} is not verbatim: {value[:50]!r}")

    return problems


def build_user_message(sample):
    """Only include fields that are present - absent fields are omitted."""
    lines = []
    if sample.get("motion"):
        lines.append(f"motion: {sample['motion']}")
    if sample.get("side"):
        lines.append(f"side: {sample['side']}")
    lines.append(f"submission:\n{sample['text']}")
    return "\n".join(lines)


def grade_submission(sample):
    system_prompt = PROMPT_PATH.read_text()
    if len(system_prompt) < 500:
        raise SystemExit(
            f"System prompt at {PROMPT_PATH} is only {len(system_prompt)} chars. "
            "It is empty or truncated - paste the rubric in and save."
        )

    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": build_user_message(sample)}],
        tools=[GRADE_TOOL],
        tool_choice={"type": "tool", "name": "record_grade"},
    )


if __name__ == "__main__":
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "S1"

    samples = json.loads(SAMPLES_PATH.read_text())
    sample = next((s for s in samples if s["id"] == sample_id), None)
    if sample is None:
        raise SystemExit(f"No sample with id {sample_id!r} in {SAMPLES_PATH}")

    print(f"[prompt: {PROMPT_PATH.read_text().__len__()} chars]")
    print(f"[sample: {sample_id} | {len(sample['text'].split())} words]")

    response = grade_submission(sample)

    # Diagnostics first - before anything that can fail.
    print(f"[blocks: {[b.type for b in response.content]}]")
    print(f"[stop_reason: {response.stop_reason}]")
    print(f"[tokens in: {response.usage.input_tokens} out: {response.usage.output_tokens}]")

    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    if not tool_blocks:
        print("\n!! No tool_use block returned.")
        if response.stop_reason == "max_tokens":
            print("   stop_reason is max_tokens - raise MAX_TOKENS and retry.")
        sys.exit(1)

    grade = tool_blocks[0].input
    computed = score_grade(grade, sample["text"])

    print("\n" + json.dumps({**grade, **computed}, indent=2, ensure_ascii=False))

    problems = validate(grade, sample["text"])
    print("\n--- validation ---")
    print("OK" if not problems else "\n".join("!! " + p for p in problems))

    if sample.get("coach"):
        print("\n--- coach reference (OLD 4-dim rubric, ranking check only) ---")
        print(sample["coach"])