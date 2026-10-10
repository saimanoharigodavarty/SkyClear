"""Step 4: explanation and citations.

OWNER: LLM teammate. The LLM explains and picks citations from retrieved passages only.
Build summary with the template below first; add the Ollama call behind config.USE_LLM.
"""
import config

NEXT_STEPS = {
    "can_fly": ["Confirm on the official portal and with local authorities before flying."],
    "permission_needed": ["Apply for permission on the official portal before flying."],
    "prohibited": ["Do not fly here. Choose another location or time."],
    "cannot_determine": ["Our data does not cover this spot. Ask the local authority or the official portal."],
}


def template_summary(verdict, zones, notices):
    inside = [z["name"] for z in zones if z["inside"]]
    if verdict == "cannot_determine":
        return "We cannot determine the rules for this spot from our data."
    if verdict == "can_fly" and not inside and not notices:
        return "No restriction found in our data for this spot, drone and time."
    parts = []
    if inside:
        parts.append("This spot is inside: " + ", ".join(inside) + ".")
    if notices:
        parts.append("An active notice applies: " + ", ".join(n["title"] for n in notices) + ".")
    return " ".join(parts) + " See the cited rules below."


def validate_citations(cited_ids, retrieved_rules):
    """Drop any rule id the LLM returned that was not in the retrieved passages."""
    allowed = {r["rule_id"] for r in retrieved_rules}
    return [i for i in cited_ids if i in allowed]


def explain(verdict, zones, notices, used_rules):
    """Return (summary, cited_rule_ids). TODO: when config.USE_LLM, ask Ollama and validate_citations()."""
    return template_summary(verdict, zones, notices), [r["rule_id"] for r in used_rules]
