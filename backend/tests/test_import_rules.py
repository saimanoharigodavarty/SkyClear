import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ingestion"))
import import_rules as ir  # noqa: E402

GOOD = {"rule_id": "R-201", "zone_type": "airport", "drone_classes": "nano;micro", "effect": "permission_needed",
        "text": "Flying inside the airport zone needs permission from the airport authority first.", "effective_from": "2021-08-25",
        "source": "Drone Rules 2021, Ministry of Civil Aviation", "section": "Rule 21"}


def test_a_good_row_passes_and_keeps_the_section_in_the_source():
    rules, problems = ir.check_rows([GOOD])
    assert not problems and rules[0]["drone_classes"] == ["nano", "micro"] and rules[0]["source"].endswith("Rule 21")


def test_every_kind_of_mistake_is_reported_with_its_row():
    bad = {**GOOD, "rule_id": "x", "zone_type": "moon", "effect": "maybe", "drone_classes": "huge", "text": "Sample paraphrase: short", "effective_from": "25/08/2021", "source": "Sample source"}
    _, problems = ir.check_rows([GOOD, bad])
    joined = "\n".join(problems)
    for word in ("rule_id must look", "zone_type must be", "effect must be", "drone_classes must", "text must be", "effective_from must", "source must name"):
        assert word in joined, word
    assert all(p.startswith("row 3") for p in problems)


def test_duplicate_ids_are_refused_including_ones_already_in_the_file():
    _, p1 = ir.check_rows([GOOD, GOOD])
    _, p2 = ir.check_rows([GOOD], existing_ids=["R-201"])
    assert any("twice" in p for p in p1) and any("twice" in p for p in p2)


def test_merge_keeps_or_replaces_the_sample_rules():
    sample = {"rule_id": "R-001", "source": "Sample source (verify against official regulation)", "text": "x"}
    real = {"rule_id": "R-201", "source": "Drone Rules 2021"}
    kept = ir.merge([sample], [GOOD])
    replaced = ir.merge([sample], [GOOD], replace_samples=True, reviewed_by="A. Reviewer")
    assert [r["rule_id"] for r in kept] == ["R-001", "R-201"] and [r["rule_id"] for r in replaced] == ["R-201"] and replaced[0]["reviewed_by"] == "A. Reviewer"


def test_the_template_row_is_not_accepted_as_a_real_rule():
    import csv
    rows = list(csv.DictReader(open(Path(ir.RULES).parent / "rules_template.csv", newline="", encoding="utf-8")))
    _, problems = ir.check_rows(rows)
    assert problems
