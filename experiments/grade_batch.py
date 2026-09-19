import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from grade_one import (
    DIMENSIONS, PROMPT_PATH, grade_submission, score_grade, validate,
)

IN_PATH = Path("experiments/argument_classic.json")
OUT_PATH = Path("experiments/runs/batch.jsonl")


def run(samples):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prompt_chars = len(PROMPT_PATH.read_text())

    # Append mode, flushed after every line: a crash or Ctrl-C never loses
    # work already paid for.
    with OUT_PATH.open("a", encoding="utf-8") as out:
        for n, sample in enumerate(samples, 1):
            tag = f"[{n}/{len(samples)}] {sample['id']} ({sample['words']}w)"
            try:
                response = grade_submission(sample)
                blocks = [b for b in response.content if b.type == "tool_use"]
                if not blocks:
                    print(f"{tag} NO TOOL CALL ({response.stop_reason})")
                    continue

                grade = blocks[0].input
                computed = score_grade(grade, sample["text"])
                problems = validate(grade, sample["text"])

                record = {
                    "id": sample["id"],
                    "words": sample["words"],
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                    "prompt_version": PROMPT_PATH.name,
                    "prompt_chars": prompt_chars,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "problems": problems,
                    **grade,
                    **computed,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()

                warn = f"  !!{len(problems)}" if problems else ""
                print(f"{tag} total={computed['total']} {computed['label']}{warn}")

            except Exception as exc:
                print(f"{tag} ERROR {type(exc).__name__}: {exc}")
                time.sleep(2)


def summarise():
    lines = [l for l in OUT_PATH.read_text().splitlines() if l.strip()]
    records = [json.loads(l) for l in lines]
    scored = [r for r in records if r["sufficient"]]

    print("\n" + "=" * 52)
    print(f"graded: {len(records)}    sufficient: {len(scored)}")

    if not scored:
        return

    print("\nscore distribution per dimension:")
    for d in DIMENSIONS:
        counts = {s: 0 for s in range(1, 6)}
        for r in scored:
            counts[r["scores"][d]] += 1
        bar = "  ".join(f"{s}:{counts[s]:<3}" for s in range(1, 6))
        mean = sum(r["scores"][d] for r in scored) / len(scored)
        print(f"  {d:<10} {bar}   mean {mean:.2f}")

    totals = sorted(r["total"] for r in scored)
    print(f"\ntotals: min {totals[0]}  median {totals[len(totals)//2]}  max {totals[-1]}")
    print(f"all totals: {totals}")

    print("\nlabel distribution:")
    for name in ["Competition-ready", "Solid", "Developing", "Foundations"]:
        n = sum(1 for r in scored if r["label"] == name)
        pct = 100 * n / len(scored)
        print(f"  {name:<20} {n:>3}  {pct:>5.1f}%  {'#' * int(pct / 2)}")

    weighed = sum(1 for r in scored if r["weighing_attempted"])
    print(f"\nweighing attempted: {weighed}/{len(scored)}")

    bad = [r for r in records if r["problems"]]
    print(f"validation problems: {len(bad)}/{len(records)}")
    for r in bad[:10]:
        print(f"  {r['id']}: {r['problems']}")

    cost = sum(r["input_tokens"] for r in records) / 1e6 * 3
    cost += sum(r["output_tokens"] for r in records) / 1e6 * 15
    print(f"\nestimated cost: ${cost:.2f}")


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
    run(samples)
    summarise()