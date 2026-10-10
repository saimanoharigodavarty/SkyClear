# Working together

The base runs end to end on local JSON files, so nobody is blocked on anyone else. Pick an area, work in your own files, merge small and often.

## Setup (once)

See "Running it" in README.md. Short version: copy .env.example to .env, `docker compose up -d`, `python backend/load_data.py`, then `uvicorn main:app --reload` from backend/. Ollama runs on the other laptop, set OLLAMA_URL in your .env.

## Areas and owners

| Area | Files | Task |
|---|---|---|
| Data and search | backend/load_data.py, backend/search.py, data/*.json | Real zones and rules, verify rule text, real notices source, tune hybrid search |
| Rules and verdict | backend/verdict.py, data/rules.json | Verdict logic for real regulation, edge cases, time-of-day rules |
| LLM | backend/explain.py | Tune the prompt and model on the remote Ollama, check summaries against verdicts |
| Frontend | frontend/ | Map polish, states, accessibility. Follow DESIGN_RULES.md |
| Eval and demo | backend/eval.py, data/eval_cases.json | 20 cases, metrics, vector vs hybrid comparison |

Write your name next to your area here when you take it.

## Rules

- The API shape in API.md is the contract. Change it only after telling everyone, and update API.md in the same commit.
- Keep the store interface in search.py (zones_near, notices_at, rules_for). The pipeline in main.py depends on it.
- Code decides the verdict. The LLM only explains and cites.
- Work directly on main with small commits, and `git pull --rebase` before you push.
- Run `python -m pytest backend` (and `USE_MONGO=1 python -m pytest backend` if you touched search or storage) and `./scripts/check_design.sh` before every push.
- Never commit .env or real secrets.
