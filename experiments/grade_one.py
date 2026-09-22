import json
import sys
from pathlib import Path

from versytalks_grader.grader import grade

SAMPLES_PATH = Path("experiments/samples.json")

if __name__ == "__main__":
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "S1"

    samples = json.loads(SAMPLES_PATH.read_text())
    sample = next((s for s in samples if s["id"] == sample_id), None)
    if sample is None:
        raise SystemExit(f"No sample with id {sample_id!r}")

    result, meta = grade(sample["text"], sample.get("motion"), sample.get("side"))

    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\n--- meta ---")
    print(json.dumps(meta, indent=2))

    if sample.get("coach"):
        print("\n--- coach reference (OLD rubric, ranking only) ---")
        print(sample["coach"])