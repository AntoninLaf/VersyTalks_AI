import json
from pathlib import Path

import pandas as pd

XLSX = Path("data/versytalks-export.xlsx")
OUT = Path("experiments/argument_classic.json")

# The export's column headers do not describe their contents - the nested config
# JSON was flattened positionally. These are the columns that actually hold the
# data for ARGUMENT_CLASSIC rows, verified by inspection.
COL_TEXT = "config.arguments.3.explanation"
COL_MOTION = "config.strategicResponse"

df = pd.read_excel(XLSX, sheet_name="Drill Submissions")
rows = df[df["Drill Type"] == "ARGUMENT_CLASSIC"]

records = []
for i, row in rows.iterrows():
    text = str(row[COL_TEXT]).strip()
    motion = row[COL_MOTION]
    records.append({
        "id": f"A{i:03d}",
        "motion": str(motion).strip() if pd.notna(motion) else None,
        "side": None,
        "status": row["Status"],
        "words": len(text.split()),
        "text": text,
    })

OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))

print(f"wrote {len(records)} submissions to {OUT}")
print(f"  with motion:   {sum(1 for r in records if r['motion'])}")
print(f"  SUBMITTED:     {sum(1 for r in records if r['status'] == 'SUBMITTED')}")
print(f"  >= 40 words:   {sum(1 for r in records if r['words'] >= 40)}")