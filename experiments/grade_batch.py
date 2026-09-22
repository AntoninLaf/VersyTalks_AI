import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from versytalks_grader.grader import PROMPT_PATH, grade
from versytalks_grader.rubric import DIMENSIONS, normalise, score_grade, validate

IN_PATH = Path("experiments/argument_classic.json")
OUT_PATH = Path("experiments/runs/batch.jsonl")

# Per million tokens. Check these against the console pricing page.
RATE_INPUT = 3.00
RATE_OUTPUT = 15.00
RATE_CACHE_READ = 0.30      # cached input is roughly a tenth of normal input
RATE_CACHE_WRITE = 3.75     # writing the cache costs a little more than input


def run(samples):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Append mode, flushed after every line: a crash or Ctrl-C never loses
    # work already paid for.
    with OUT_PATH.open("a", encoding="utf-8") as out:
        for n, sample in enumerate(samples, 1):
            tag = f"[{n}/{len(samples)}] {sample['id']} ({sample['words']}w)"
            try:
                result, meta = grade(
                    sample["text"], sample.get("motion"), sample.get("side")
                )

                record = {
                    "id": sample["id"],
                    "words": sample["words"],
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                    **meta,
                    **result,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()

                notes = []
                if result["problems"]:
                    notes.append(f"!!{len(result['problems'])}")
                if meta["attempts"] > 1:
                    notes.append(f"retry x{meta['attempts']}")
                if meta["stripped_fields"]:
                    notes.append(f"stripped {','.join(meta['stripped_fields'])}")
                suffix = ("  " + "  ".join(notes)) if notes else ""

                print(
                    f"{tag} total={result['total']} {result['label']}"
                    f"  {meta['latency_ms']}ms{suffix}"
                )

            except Exception as exc:
                print(f"{tag} ERROR {type(exc).__name__}: {exc}")
                time.sleep(2)


def summarise():
    texts = {s["id"]: s["text"] for s in json.loads(IN_PATH.read_text())}

    lines = [l for l in OUT_PATH.read_text().splitlines() if l.strip()]
    records = [json.loads(l) for l in lines]

    # Recompute everything derived, with today's code, at zero cost.
    # The API calls are the expensive part and they are already paid for.
    for r in records:
        text = texts.get(r["id"], "")
        problems = normalise(r)
        problems += validate(r, text)
        r["problems"] = problems
        r.update(score_grade(r, text))

    scored = [r for r in records if r["sufficient"]]

    print("\n" + "=" * 52)
    print(f"graded: {len(records)}    sufficient: {len(scored)}")

    if not scored:
        return

    print("\nscore distribution per dimension:")
    for d in DIMENSIONS:
        counts = {s: 0 for s in range(1, 6)}
        for r in scored:
            value = r["scores"][d]
            if value in counts:
                counts[value] += 1
        bar = "  ".join(f"{s}:{counts[s]:<3}" for s in range(1, 6))
        mean = sum(r["scores"][d] for r in scored) / len(scored)
        print(f"  {d:<10} {bar}   mean {mean:.2f}")

    totals = sorted(r["total"] for r in scored)
    print(f"\ntotals: min {totals[0]}  median {totals[len(totals) // 2]}  max {totals[-1]}")
    print(f"all totals: {totals}")

    print("\nlabel distribution:")
    for name in ["Strong", "Solid", "Developing", "Foundations"]:
        n = sum(1 for r in scored if r["label"] == name)
        pct = 100 * n / len(scored)
        print(f"  {name:<14} {n:>3}  {pct:>5.1f}%  {'#' * int(pct / 2)}")

    weighed = sum(1 for r in scored if r["weighing_attempted"])
    print(f"\nweighing attempted: {weighed}/{len(scored)}")

    retried = sum(1 for r in records if r.get("attempts", 1) > 1)
    stripped = sum(1 for r in records if r.get("stripped_fields"))
    print(f"needed a retry:     {retried}/{len(records)}")
    print(f"had a field stripped: {stripped}/{len(records)}")

    latencies = sorted(r["latency_ms"] for r in records if "latency_ms" in r)
    if latencies:
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95) - 1]
        print(f"latency: median {p50}ms   p95 {p95}ms   max {latencies[-1]}ms")

    bad = [r for r in records if r["problems"]]
    print(f"\nvalidation problems: {len(bad)}/{len(records)}")
    for r in bad[:10]:
        print(f"  {r['id']}: {r['problems']}")

    cost = 0.0
    for r in records:
        cost += r.get("input_tokens", 0) / 1e6 * RATE_INPUT
        cost += r.get("output_tokens", 0) / 1e6 * RATE_OUTPUT
        cost += r.get("cache_read_tokens", 0) / 1e6 * RATE_CACHE_READ
        cost += r.get("cache_write_tokens", 0) / 1e6 * RATE_CACHE_WRITE

    cache_read = sum(r.get("cache_read_tokens", 0) for r in records)
    cache_write = sum(r.get("cache_write_tokens", 0) for r in records)
    print(f"\ncache: {cache_write} written, {cache_read} read")
    print(f"estimated cost: ${cost:.2f}   (${cost / max(len(records), 1):.4f} per grade)")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summarise()
        sys.exit(0)

    samples = json.loads(IN_PATH.read_text())
    samples = [s for s in samples if s["status"] == "SUBMITTED"]

    if "--limit" in sys.argv:
        samples = samples[: int(sys.argv[sys.argv.index("--limit") + 1])]

    if "--repeat" in sys.argv:
        n = int(sys.argv[sys.argv.index("--repeat") + 1])
        samples = [s for s in samples for _ in range(n)]

    print(f"grading {len(samples)} submissions -> {OUT_PATH}")
    print(f"rubric: {PROMPT_PATH.name}")
    run(samples)
    summarise()