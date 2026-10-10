# Working together

The base runs end to end on local JSON files, so nobody is blocked on anyone else. Pick an area, work in your own files, merge small and often.

## Setup (once)

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env        # then export the values, or set them in your shell
cd backend && uvicorn main:app --reload
```

Open http://localhost:8000. Tests: `python -m pytest backend`. Evaluation: `cd backend && python eval.py`.

## Areas and owners

| Area | Files | Task |
|---|---|---|
| Data and search | backend/load_data.py, backend/search.py (MongoStore), data/*.json | Load into MongoDB, embeddings, indexes, geo/vector/hybrid queries, real zones and rules |
| Rules and verdict | backend/verdict.py, data/rules.json | Verdict logic for real regulation, edge cases, time-of-day rules |
| LLM | backend/explain.py | Ollama explanation, citation selection, citation validation |
| Frontend | frontend/ | Map polish, states, accessibility. Follow DESIGN_RULES.md |
| Eval and demo | backend/eval.py, data/eval_cases.json | 20 cases, metrics, vector vs hybrid comparison |

Write your name next to your area here when you take it.

## Rules

- The API shape in API.md is the contract. Change it only after telling everyone, and update API.md in the same commit.
- Keep the store interface in search.py (zones_near, notices_at, rules_for). The pipeline in main.py depends on it.
- Code decides the verdict. The LLM only explains and cites.
- Run `python -m pytest backend` and `./scripts/check_design.sh` before every push.
- Branch per task (`feat/<area>-<thing>`), small pull requests, pull main before you start.
- Never commit .env or real secrets.
