# Results

Real measurements only. Every number here came from a run, with the date and setup. Re-run `cd backend && USE_MONGO=1 python eval.py` after any change to rules, zones or search and update this file. Do not quote numbers in a pitch that are not in here.

## Setup of the runs below (10 Oct 2026)

- App and MongoDB (Atlas Local in Docker) on a Mac.
- Language model and embeddings on a separate Windows laptop over Wi-Fi, CPU only: `qwen2.5:3b` and `nomic-embed-text` (768 dimensions) through Ollama.
- Data: 156 zones, 7 sample rules (placeholder paraphrase, not the real regulation), 20 evaluation cases.

## Verdict accuracy (code decides, no model involved)

| Metric | Result |
|---|---|
| Verdict accuracy | 20 of 20 |
| False-safe (said "can fly" when it should not) | 0 of 20 |
| Citation recall (expected rule is in the citations) | 14 of 14 |

## Rule retrieval: keyword vs vector vs hybrid

8 questions, each with one expected rule. "Recall at k" counts how often the expected rule is in the top k results.

| Method | Recall at 1 | Recall at 3 |
|---|---|---|
| Keyword (Atlas Search, English analyzer) | 7 of 8 | 8 of 8 |
| Vector (Atlas Vector Search, nomic-embed-text) | 6 of 8 | 7 of 8 |
| Hybrid (`$rankFusion` of both, inside MongoDB) | 6 of 8 | 8 of 8 |

Read this with care. There are only 7 rules and 8 questions, so one question changes a result by 12 points. Keyword search wins at the top here because the sample rules share words with the questions. These numbers say nothing yet about the real regulation. Re-run them once the real corpus (hundreds of passages) is loaded, that is where vector and hybrid search are expected to pull ahead.

## Relevance gate for Ask

Vector search always returns its nearest rules, even for a question about pizza, so Ask answers only when keywords match or the best vector similarity reaches `ASK_MIN_SCORE` (0.78).

| Question | Best vector similarity |
|---|---|
| Related to the rules (4 questions) | 0.80 to 0.91 |
| Unrelated: pizza, cake, cricket | 0.71 to 0.76 |

The gap is small and measured on 8 questions. Recalibrate with the eval once there are more rules and questions.

## Speed (Windows laptop, CPU only)

| Step | Time |
|---|---|
| Embedding one question | about 1.2 s |
| Answer from `qwen2.5:3b` | about 6 to 12 s (about 9 tokens per second) |
| Check: verdict shown | immediately |
| Check: AI explanation fills in | about 10 to 16 s later |
| Ask with the AI model | about 8 to 12 s |

The verdict never waits for the model. A faster machine or a GPU would cut these a lot.

## What the small model got wrong, and what stops it

Found by running real questions, not by guessing. Each one now has a guard and a test.

| Observed | Guard |
|---|---|
| Wrote "not allowed" for a permission-needed spot | Wording rules per verdict reject it and use the plain explanation |
| Wrote that micro drones can fly over a nearby airport and park | An explanation may not name zones the pilot is not inside |
| Repeated our prompt labels ("the SPOT FACTS provided") | Label leaks are rejected |
| Said a VIP movement needs permission, citing the wrong rule | The restriction rule now mentions VIP movements, so retrieval finds it first. Better retrieval from the real corpus will help further |
| Answered a night-flying question with unrelated rules as if they were the answer | Without a direct answer, Ask says "These are the closest rules we hold, check that they answer your question" |

The model is a small one. The rule is: it may only reword what the rules and the rule engine already say, and anything doubtful falls back to the plain text. The verdict is always decided by code.

## Additional safety regression (Windows / Atlas, 10 Oct 2026)

- 454 OSM-derived zones, 9 rules (including two attributable Digital Sky airspace rules), and 32 evaluation cases.
- Deterministic verdict accuracy: 32/32; false-safe: 0/32; citation recall: 18/18.
- Keyword retrieval: recall@1 8/12 and recall@3 12/12.
- The remote Ollama endpoint was unreachable in this run, so vector and true `$rankFusion` hybrid results were not measured. The fallback used keyword search only.
- Automated local suite: 130 passed, 7 skipped. MongoDB integration had previously passed 133 with 1 expected autocomplete-index skip; rerun it after loading an official geometry export.


## Load test (10 Oct 2026, after gzip, zone caching and the geofence speed-up)

Run with `.venv/bin/python scripts/loadtest.py`. One uvicorn process, MongoDB in Docker, the load generator on the same Mac, so the generator takes CPU from the server. 8 seconds per row. No AI calls in these runs (`explain: false`).

| Endpoint | Concurrent users | Requests per second | p50 (ms) | p95 (ms) | p99 (ms) | Errors |
|---|---|---|---|---|---|---|
| POST /check (zone + rules, no AI) | 10 | 372 | 26 | 44 | 58 | 0 |
| POST /check (zone + rules, no AI) | 50 | 394 | 126 | 170 | 201 | 0 |
| POST /check (zone + rules, no AI) | 200 | 396 | 522 | 661 | 718 | 0 |
| GET /zones?bbox (2dsphere) | 10 | 678 | 14 | 24 | 36 | 0 |
| GET /zones?bbox (2dsphere) | 50 | 353 | 76 | 537 | 980 | 0 |
| GET /zones?bbox (2dsphere) | 200 | 146 | 789 | 5283 | 6412 | 0 |
| GET /live/drones | 10 | 1628 | 5 | 7 | 22 | 0 |
| GET /live/drones | 50 | 411 | 59 | 452 | 896 | 1 |
| GET /live/drones | 200 | 177 | 611 | 4959 | 5878 | 1 |

Simulator tick (in process, 1 second step):

| Simulated drones | Tick time (ms), median of 20 | Worst of 20 (ms) |
|---|---|---|
| 100 | 27.5 | 60.6 |
| 500 | 123.5 | 174.8 |
| 1000 | 244.6 | 375.5 |

How to read it:

- The check holds about 390 requests per second from 50 to 200 users. At 200 users the 95th percentile is 661 ms with no errors. Before the changes the same row was 106 requests per second and a 95th percentile of 6.5 s.
- The zone map and the live drone list still queue at 200 users (95th percentile about 5 s), and each had 1 failed request in some rows. One process handles one request at a time per thread, and these two return the most data. More processes behind Nginx is the next step, but the simulator and the event channel keep state in one process, so the simulator must be split out first. That has not been done or measured.
- Before the geofence change the tick was 207 ms for 100 drones and 2.1 s for 1000. Skipping zones by bounding box and reading zones every 5 seconds instead of every tick brought 1000 drones to about 245 ms. The tick must stay under the 1 second step, so 1000 drones fits and 2000 would not.

### Same test with the simulator running 100 drones (11 Oct 2026)

The live list is now built once per simulator tick and shared by everyone who asks in that tick. With 100 drones flying on the same Mac as the load generator: the check gave 372 requests per second at 10 users and 362 at 200 users (95th percentile 1.6 s at 200); the live list gave 452 requests per second at 50 users (95th percentile 143 ms) and fell to 102 requests per second at 200 users (95th percentile 5.6 s). The zone map at 200 users gave 99 requests per second. These runs are noisy because the simulator and the load generator share the CPU with the server. The sharing of one process is still the limit at 200 users; the cache did not remove it.
