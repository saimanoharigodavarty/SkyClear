"""Import real regulation passages from a CSV, check them, and merge them into data/rules.json.

  python ingestion/import_rules.py rules.csv                 # check only, prints problems
  python ingestion/import_rules.py rules.csv --write         # add the rules (keeps the sample rules)
  python ingestion/import_rules.py rules.csv --write --replace-samples --reviewed-by "Name"

Then reload MongoDB so the new rules get embeddings and search indexes:  cd backend && python load_data.py
CSV columns: rule_id, zone_type, drone_classes (separated by ;), effect, text, effective_from (YYYY-MM-DD), source, section (optional)
Each passage must be a short paraphrase or quote from an official document, with the document and section in `source`. A person checks it, not the script.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

RULES = Path(__file__).resolve().parent.parent / "data" / "rules.json"
ZONE_TYPES = {"airport", "military", "government", "park", "notice", "digital_sky_red", "digital_sky_yellow"}
EFFECTS = {"allowed", "permission_needed", "prohibited"}
CLASSES = {"nano", "micro", "small", "medium"}


def check_rows(rows, existing_ids=()):
    """Returns (rules, problems). A problem names the row, so it can be fixed in the sheet."""
    rules, problems, seen = [], [], set(existing_ids)
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        where = f"row {n} ({(row.get('rule_id') or '?').strip()})"
        rid = (row.get("rule_id") or "").strip()
        if not re.fullmatch(r"R-[A-Za-z0-9-]{1,12}", rid):
            problems.append(f"{where}: rule_id must look like R-101 or R-101B")
        elif rid in seen:
            problems.append(f"{where}: rule_id is used twice")
        seen.add(rid)
        zt, ef = (row.get("zone_type") or "").strip(), (row.get("effect") or "").strip()
        if zt not in ZONE_TYPES:
            problems.append(f"{where}: zone_type must be one of {', '.join(sorted(ZONE_TYPES))}")
        if ef not in EFFECTS:
            problems.append(f"{where}: effect must be one of {', '.join(sorted(EFFECTS))}")
        classes = [c.strip() for c in (row.get("drone_classes") or "").split(";") if c.strip()]
        if not classes or any(c not in CLASSES for c in classes):
            problems.append(f"{where}: drone_classes must list some of {', '.join(sorted(CLASSES))} separated by ;")
        text = " ".join((row.get("text") or "").split())
        if not 25 <= len(text) <= 600:
            problems.append(f"{where}: text must be 25 to 600 characters, it is {len(text)}")
        if re.search(r"sample paraphrase|lorem|todo|tbd|your own words", text, re.I):
            problems.append(f"{where}: text still looks like a placeholder")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", (row.get("effective_from") or "").strip()):
            problems.append(f"{where}: effective_from must be YYYY-MM-DD")
        source = " ".join((row.get("source") or "").split())
        if len(source) < 8 or re.search(r"sample source|name of the official", source, re.I):
            problems.append(f"{where}: source must name the official document")
        section = (row.get("section") or "").strip()
        rules.append({"rule_id": rid, "zone_type": zt, "drone_classes": classes, "effect": ef, "text": text,
                      "effective_from": (row.get("effective_from") or "").strip(), "source": source + (f", {section}" if section else "")})
    return rules, problems


def merge(existing, new, replace_samples=False, reviewed_by=None):
    """The rules file after the import. Sample rules are kept unless asked to replace them."""
    keep = [r for r in existing if not (replace_samples and str(r.get("source", "")).lower().startswith("sample"))]
    added = [{**r, "reviewed_by": reviewed_by} if reviewed_by else {**r, "reviewed_by": None} for r in new]
    return keep + added


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv"); ap.add_argument("--write", action="store_true"); ap.add_argument("--replace-samples", action="store_true"); ap.add_argument("--reviewed-by")
    a = ap.parse_args()
    existing = json.loads(RULES.read_text(encoding="utf-8"))
    with open(a.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [r["rule_id"] for r in existing if not (a.replace_samples and str(r.get("source", "")).lower().startswith("sample"))]
    rules, problems = check_rows(rows, ids)
    if problems:
        print("\n".join(problems)); print(f"\n{len(problems)} problem(s). Nothing was written."); sys.exit(1)
    if not a.write:
        print(f"{len(rules)} rule(s) look fine. Add --write to save them."); return
    out = merge(existing, rules, a.replace_samples, a.reviewed_by)
    RULES.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved. {len(out)} rules in data/rules.json. Now run: cd backend && python load_data.py" + ("" if a.reviewed_by else "\nNote: no --reviewed-by was given, so these rules are marked as not reviewed."))


if __name__ == "__main__":
    main()
