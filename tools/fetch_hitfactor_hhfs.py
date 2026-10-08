"""Fill in HHFs that USPSA's 2025 HHF report leaves out, from hitfactor.info.

Usage: python3 tools/fetch_hitfactor_hhfs.py

Run after tools/build_data.py. For every 25- and 26-series classifier it takes the
"Cur. HHF" that hitfactor.info shows on /classifiers/<division>/<code>. Classifiers
with no current HHF there (the 26-series trials) get its "Rec. HHF" instead, an
estimate hitfactor.info computes from the scores so far, flagged as hhfEstimate.
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "classifiers.json")
SITE = "https://www.hitfactor.info"
SERIES = ("25-", "26-")
# hitfactor.info division ids. Limited-10 is left out on purpose: USPSA scores it
# against the Limited HHFs, so it copies Limited below.
DIVISIONS = {
    "open": "opn", "limited": "ltd", "limited-optics": "lo", "carry-optics": "co",
    "production": "prod", "single-stack": "ss", "revolver": "rev", "pcc": "pcc",
}


def site_hhfs(division):
    """Each classifier's Cur. HHF, falling back to Rec. HHF, as (hhf, is_estimate)."""
    with urllib.request.urlopen(f"{SITE}/api/classifiers/{division}") as r:
        rows = json.load(r)
    out = {}
    for row in rows:
        if (row.get("curHHF") or -1) > 0:
            out[row["classifier"]] = (row["curHHF"], False)
        elif (row.get("recHHF") or -1) > 0:
            out[row["classifier"]] = (row["recHHF"], True)
    return out


def main():
    data = json.load(open(DATA))
    found = {ours: site_hhfs(theirs) for ours, theirs in DIVISIONS.items()}
    for c in data["classifiers"]:
        if not c["code"].startswith(SERIES):
            continue
        hits = {d: found[d][c["code"]] for d in DIVISIONS if c["code"] in found[d]}
        hhf = {d: round(v, 4) for d, (v, _) in hits.items()}
        if "limited" in hhf:
            hhf["limited-10"] = hhf["limited"]
        c["hhf"] = hhf
        if hhf:
            c["hhfSource"] = f"{SITE}/classifiers/{DIVISIONS['carry-optics']}/{c['code']}"
        else:
            c.pop("hhfSource", None)
        if any(est for _, est in hits.values()):
            c["hhfEstimate"] = True
        else:
            c.pop("hhfEstimate", None)
    with open(DATA, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
