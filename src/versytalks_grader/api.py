"""HTTP service. One endpoint VersyTalks calls, plus a health check."""

import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from versytalks_grader import store
from versytalks_grader.grader import MODEL, PROMPT_PATH, grade

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grader")

MAX_PER_USER = int(os.environ.get("GRADER_MAX_PER_USER", "5"))
MAX_TOTAL = int(os.environ.get("GRADER_MAX_TOTAL", "500"))
API_KEY = os.environ.get("GRADER_API_KEY", "")

app = FastAPI(title="VersyTalks Debate Assistant", version="1.1.0")


class GradeRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    submission_id: str = Field(min_length=1, max_length=128)
    submission: str = Field(min_length=1, max_length=20000)
    motion: str | None = Field(default=None, max_length=2000)
    side: str | None = Field(default=None, max_length=64)
    drill_type: str = "ARGUMENT_CLASSIC"


def check_key(provided):
    """Constant-time comparison: a normal == leaks the key one character at a time."""
    if not API_KEY:
        raise HTTPException(500, "GRADER_API_KEY is not configured on the server")
    if not provided or not secrets.compare_digest(provided, API_KEY):
        raise HTTPException(401, "invalid or missing X-API-Key")


def to_payload(result, meta, quota_used):
    """Split what the debater sees from what VersyTalks stores but never renders."""
    if not result["sufficient"]:
        return {
            "status": "insufficient",
            "reason": result["insufficient_reason"],
            "quota": {"used": quota_used, "limit": MAX_PER_USER},
            "internal": {
                "flags": result["flags"],
                "model": meta["model"],
                "rubric_version": meta["prompt_version"],
            },
        }

    return {
        "status": "graded",
        "quota": {"used": quota_used, "limit": MAX_PER_USER},
        "feedback": {
            "label": result["label"],
            "total": result["total"],
            "max_total": 20,
            "scores": result["scores"],
            "strongest_moment": result["strongest_moment"],
            "biggest_gap": result["biggest_gap"],
            "one_fix": result["one_fix"],
            "rewrite_example": result["rewrite_example"],
            "weighing_attempted": result["weighing_attempted"],
        },
        "internal": {
            "anchor_evidence": result["anchor_evidence"],
            "flags": result["flags"],
            "confidence": result["confidence"],
            "problems": result["problems"],
            "model": meta["model"],
            "rubric_version": meta["prompt_version"],
            "latency_ms": meta["latency_ms"],
            "attempts": meta["attempts"],
            "stripped_fields": meta["stripped_fields"],
        },
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL,
        "rubric": PROMPT_PATH.name,
        "max_per_user": MAX_PER_USER,
        "max_total": MAX_TOTAL,
    }


@app.post("/grade")
def grade_endpoint(req: GradeRequest, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)

    # Idempotency first: a retried request must never be graded or charged twice.
    existing = store.find(req.submission_id)
    if existing:
        result, meta = existing
        log.info("cached submission_id=%s user=%s", req.submission_id, req.user_id)
        return to_payload(result, meta, store.count_for_user(req.user_id))

    used = store.count_for_user(req.user_id)
    if store.count_total() >= MAX_TOTAL:
        raise HTTPException(
            429,
            detail={
                "error": "beta_capacity_reached",
                "message": "The beta has reached its grading limit.",
            },
        )

    try:
        result, meta = grade(req.submission, req.motion, req.side)
    except Exception as exc:
        # The debater's quota is not consumed when we fail. Storage happens
        # only on success, so nothing to undo.
        log.exception("grading failed submission_id=%s", req.submission_id)
        raise HTTPException(
            503,
            detail={
                "error": "grading_failed",
                "message": "The grader is temporarily unavailable. Please try again.",
            },
        ) from exc

    store.save(req.submission_id, req.user_id, req.drill_type, result, meta)

    log.info(
        "graded submission_id=%s user=%s total=%s label=%s %dms attempts=%d",
        req.submission_id, req.user_id, result["total"], result["label"],
        meta["latency_ms"], meta["attempts"],
    )

    return to_payload(result, meta, used + 1)