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
