# Working together

The base runs end to end on local JSON files, so nobody is blocked on anyone else. Pick an area, work in your own files, merge small and often.

## Setup (once)

See "Running it" in README.md. Short version: copy .env.example to .env, `docker compose up -d`, `python backend/load_data.py`, then `uvicorn main:app --reload` from backend/. Ollama runs on the other laptop, set OLLAMA_URL in your .env.

## Workstreams

Seven streams, each with its own files, so everyone works at the same time without merge fights. Priority: P0 must be done for the demo, P1 should be, P2 if time remains. Write the owner's name in the Owner column.

| # | Stream | Owner | Files (only this person edits) | Tasks | Done when |
|---|---|---|---|---|---|
| 1 | Rules and legal data | ____ | data/rules.json, data/notices.json | P0: replace placeholder rule text with the real regulation (cite section and date). P0: decide the notices source (authority entry only, no scraping). P1: add rules for night flight, altitude limit, no-fly during events | Every rule has a real source and effective date. No text says "Sample" |
| 2 | Zones data | ____ | data/zones_manual.geojson, backend/build_zones.py | P0: add real Hyderabad zones (Secretariat, Raj Bhavan, DRDO, ECIL, Ramoji, stadiums, prisons) with rule_ids and sources. P1: replace circle airports with real airspace polygons if found. P1: add zone height limits | Map shows 25 or more real Hyderabad zones, each labeled with a source |
| 3 | LLM and embeddings | ____ | backend/explain.py, backend/embeddings.py, backend/load_data.py | P0: connect to the remote Ollama (OLLAMA_URL, USE_LLM=1), run load_data.py, check the vector index builds. P0: tune the prompt on qwen2.5 until summaries are correct on all 20 eval cases. P1: add a test with 10 adversarial notice texts (prompt injection) | explained_by is "llm" for most checks, never contradicts the verdict, injection tests pass |
| 4 | Search and evaluation | ____ | backend/search.py, backend/eval.py, data/eval_cases.json | P0: run eval.py against MongoDB with embeddings and record real vector, text, hybrid numbers in docs/RESULTS.md. P0: add eval cases to reach 30, including hard ones (zone edges, overlapping zones, notice boundaries). P1: tune hybrid fusion and k | docs/RESULTS.md has real numbers, 30 cases, 0 false-safe |
| 5 | Platform backend | ____ | backend/bridge.py, backend/runtime.py, backend/main.py | P0: MongoDB change stream on notices that creates alerts (replace the call in publish_notice). P0: rate limiting and input caps. P1: email alerts (SMTP or ntfy). P1: alert when a rule or zone changes. P2: audit log for official actions | Publishing a notice from a second terminal alerts a pilot within 2 seconds, with no call from the API handler |
| 6 | Route and verdict engine | ____ | backend/verdict.py, backend/sim.py, backend/geo.py, backend/tests/test_verdict.py | P0: PRODUCT.md A3 (route sampling can skip narrow zones, use segment against polygon intersection) and A4, A5, A6. P1: altitude and day or night in the verdict. P1: corridor buffer around routes | A narrow corridor notice on a route is always caught, with tests |
| 7 | Frontend: pilot and official pages | ____ | frontend/pilot.js, frontend/official.js, frontend/index.html, frontend/official.html, frontend/account.html | P0: end-to-end click-through bugs and empty, loading and error states. P0: mobile layout. P1: accessibility (keyboard, contrast, labels). P1: notice preview and affected-flights count before publishing | A new person can complete check, watch, request permission and decision on a phone without help |
| 8 | Map | Nikhil | frontend/common.js (map functions), frontend/app.css (map section) | P0: rebuild the map look and feel. | Agreed with the team at demo review |
| 9 | Demo and presentation | ____ | docs/ (new), README.md | P0: 3 minute demo script, backup screen recording, slides with real numbers from docs/RESULTS.md. P0: pitch for Track 2 (RAG Engine): geo plus vector plus keyword in MongoDB, code decides, LLM explains. P1: answers to likely judge questions (use PRODUCT.md loopholes) | One full rehearsal under 3 minutes, recording saved |

Streams 1 to 7 do not touch each other's files. If you need a change in someone else's file, ask them or message in the team chat, do not edit it. Shared files (README.md, API.md, PRODUCT.md, TEAM.md) get small edits only, and always `git pull --rebase` first.

## Order of work

1. Everyone: pull, run the setup above, run the app, read PRODUCT.md for ten minutes.
2. First hour: P0 tasks start in parallel. Stream 3 and 4 need the Ollama laptop running first, so whoever owns it does that before anything else.
3. Second hour onward: P0 finish, then P1.
4. Last stretch: freeze features, run `python backend/eval.py` and both test modes, rehearse the demo twice.

## Rules

- The API shape in API.md is the contract. Change it only after telling everyone, and update API.md in the same commit.
- Keep the store interface in search.py (zones_near, notices_at, rules_for). The pipeline in main.py depends on it.
- Code decides the verdict. The LLM only explains and cites.
- Work directly on main with small commits, and `git pull --rebase` before you push.
- Run `python -m pytest backend` (and `USE_MONGO=1 python -m pytest backend` if you touched search or storage) and `./scripts/check_design.sh` before every push.
- Never commit .env or real secrets.
