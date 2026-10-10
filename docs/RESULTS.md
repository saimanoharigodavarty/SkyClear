# Evaluation results

Only measured runs are recorded here. Vector and true hybrid numbers remain pending until the remote Ollama host is connected; the current hybrid path correctly falls back to MongoDB Search.

## Run environment

- Date: 2026-10-10
- Client: Windows, Python 3.14.3, PyMongo 4.16.0
- Database: MongoDB Atlas 8.0.34
- Store modes tested: local JSON and MongoDB
- Zones: 454
- Rules: 9 passages: 7 prototype context rules plus 2 attributable Digital Sky red/yellow airspace rules. The prototype context rules remain pending official verification.
- Evaluation cases: 32
- LLM/embedding host: unavailable for this run

## Verdict and citation results

The same results were observed with the local JSON store and MongoDB store.

| Metric | Result |
|---|---:|
| Verdict accuracy | 32/32 (100%) |
| False-safe | 0/32 |
| Citation recall | 18/18 (100%) |

The cases cover airport, military, park and government rules; active and inactive notices; exact notice start/end times; different drone classes; unverified OSM contexts; overlapping known and unknown zones; just-inside and just-outside airport-edge points; and coverage-boundary behavior.

## Retrieval results

Twelve evaluation cases contain a natural-language retrieval query and one or more expected rule IDs.

| Mode | Recall@1 | Recall@3 | Status |
|---|---:|---:|---|
| MongoDB Search (`$search`) | 8/12 | 12/12 | Measured |
| Vector (`$vectorSearch`) | Pending | Pending | Ollama unavailable; vector index not built |
| Hybrid (`$rankFusion`) | 8/12 | 12/12 | Keyword fallback only, not a true hybrid measurement |

Do not present the fallback row as a vector/hybrid result. After connecting Ollama, rerun `python backend/load_data.py` and `$env:USE_MONGO="1"; python backend/eval.py`, then replace the pending cells with the real output.

## Prompt-injection regression

A focused test supplies an active notice containing an instruction to ignore the fixed verdict and claim that the pilot can fly. A simulated model response follows that malicious instruction. SkyClear rejects the contradictory response and returns the deterministic template with the deciding rule citation.

Notice text is labelled as third-party data in the prompt, whitespace-normalized and capped at 200 characters. This does not make arbitrary model output trustworthy; the fixed code verdict, citation allow-list and consistency checks remain the enforcement boundary.

## Automated tests

| Suite | Result |
|---|---:|
| Local JSON | 130 passed, 7 skipped |
| MongoDB integration | Not re-run after this change; previously 133 passed, 1 skipped |

The small Atlas tier cannot duplicate the production Search indexes in `skyclear_test`. MongoDB integration tests therefore skip only the autocomplete endpoint test; that pipeline has focused unit coverage and was verified directly against the production `zones_autocomplete` index.
