"""Everything that touches the outside world: the API, retries, caching."""

import os
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from versytalks_grader import rubric

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000
TIMEOUT_SECONDS = 60.0
TRANSPORT_RETRIES = 3
CONTENT_ATTEMPTS = 2

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "argument_classic_v1.md"

# The SDK already retries transport failures with backoff. Do not reimplement it.
client = Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    max_retries=TRANSPORT_RETRIES,
    timeout=TIMEOUT_SECONDS,
)

_prompt_cache = None


def system_prompt():
    """Read the rubric once per process, not once per request."""
    global _prompt_cache
    if _prompt_cache is None:
        text = PROMPT_PATH.read_text()
        if len(text) < 500:
            raise RuntimeError(f"Rubric at {PROMPT_PATH} is only {len(text)} chars.")
        _prompt_cache = text
    return _prompt_cache


def _call(submission_text, motion, side):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": system_prompt(),
            # The rubric is byte-identical on every call. Caching it server-side
            # cuts both cost and time-to-first-token on repeat requests.
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": rubric.build_user_message(submission_text, motion, side),
        }],
        tools=[rubric.GRADE_TOOL],
        tool_choice={"type": "tool", "name": "record_grade"},
    )


def grade(submission_text, motion=None, side=None):
    """Grade one submission. Returns (result, meta).

    Raises only for programmer error or exhausted transport retries. Content
    problems are handled: unverifiable quotes trigger one retry, then the
    offending field is removed rather than shown to a debater.
    """
    started = time.monotonic()
    meta = {
        "model": MODEL,
        "prompt_version": PROMPT_PATH.name,
        "attempts": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "stripped_fields": [],
    }

    grade_dict = None
    problems = []

    for attempt in range(1, CONTENT_ATTEMPTS + 1):
        meta["attempts"] = attempt
        response = _call(submission_text, motion, side)

        usage = response.usage
        meta["input_tokens"] += usage.input_tokens
        meta["output_tokens"] += usage.output_tokens
        meta["cache_read_tokens"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        meta["cache_write_tokens"] += getattr(usage, "cache_creation_input_tokens", 0) or 0

        blocks = [b for b in response.content if b.type == "tool_use"]
        if not blocks:
            if attempt < CONTENT_ATTEMPTS:
                continue
            raise RuntimeError(f"No tool call returned (stop_reason={response.stop_reason})")

        grade_dict = dict(blocks[0].input)
        meta["used_fallback_reason"] = rubric.ensure_reason(grade_dict, submission_text)
        problems = rubric.normalise(grade_dict) + rubric.validate(grade_dict, submission_text)
        problems = rubric.normalise(grade_dict)
        problems += rubric.validate(grade_dict, submission_text)

        # A bad quote is the one error worth paying for a second try.
        if not rubric.bad_quotes(grade_dict, submission_text):
            break

    meta["stripped_fields"] = rubric.strip_bad_quotes(grade_dict, submission_text)
    problems = rubric.normalise(grade_dict) + rubric.validate(grade_dict, submission_text)

    result = {**grade_dict, **rubric.score_grade(grade_dict, submission_text), "problems": problems}
    meta["latency_ms"] = int((time.monotonic() - started) * 1000)
    return result, meta