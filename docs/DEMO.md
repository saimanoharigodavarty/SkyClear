# Demo script

About 8 minutes. Every step maps to one of the six judging components. Do the setup once, before the judges arrive.

## Setup (10 minutes before)

1. Docker running, then `./run.sh` in the project folder. Open `http://localhost:8000`.
2. `cd backend && ../.venv/bin/python manage.py prepare-demo` creates two flights that are ready to fly for the next 6 hours and prints the demo pilot's password.
3. Presentation computer: sign in as the demo pilot, open `/display.html` full screen (satellite 3D).
4. Phone on the same Wi-Fi. Second window: officer console, signed in as an officer or the admin.
5. Check once: `/health` shows `"mongo": true` and `"llm": true`.

Logins are in `data/demo_credentials.txt` (not in git). Never read passwords out loud in the demo.

## The story, in order

| Min | What you do | What you say | Component |
|---|---|---|---|
| 0:00 | Open the pilot map, click a green spot, then a red zone | "A pilot asks: can I fly here? Code decides the answer from MongoDB geo data. The model only explains and cites the rule." | Technology stack |
| 1:00 | Same check, show the rule cards and the sentence the AI wrote | "Hybrid retrieval: Atlas Search keywords plus Atlas Vector Search, fused inside MongoDB with $rankFusion. If the model is off, the plain explanation still works." | AI/ML |
| 2:00 | Ask tab: "Do I need permission near an airport?", then "best pizza" | "A relevance gate refuses questions the rules do not cover. Citations are validated, the model cannot invent a rule." | AI/ML |
| 3:00 | Request permission in a yellow zone as the demo pilot | "The request is routed to the right office by zone type and distance." | Backend and API |
| 3:30 | Officer console, Requests: approve it with conditions | "One MongoDB transaction writes the permit, the flight status, the alert and the audit entry. All of it or none of it." | MongoDB |
| 4:00 | Pilot window: the permit with QR appears with no reload | "That arrived through a change stream, pushed to the browser." | MongoDB, Advanced |
| 4:30 | Display screen: preflight, take off. Scan the QR with the phone, fly with the sticks | "The phone gets a scoped 45 minute token. It can fly this one drone and nothing else." | Security |
| 5:30 | Fly out of the permit area, then past the height limit. Switch the camera to drone view | "Permit-aware geofence: yellow zones are fine inside the permit, a breach outside it. Drone view shows the distance to the nearest zone and the time to reach it." | Advanced |
| 6:30 | Officer: Live tab shows the breach. Press Recall | "The drone returns home by itself. The pilot is told why." | Backend and API |
| 7:00 | Officer: Insights tab | "Aggregations materialised with $merge. Audit log is append-only. Change stream status is live." | MongoDB |
| 7:30 | Show `docs/RESULTS.md`: accuracy, retrieval, load test | "These numbers come from runs, with the machine written next to them." | Performance |

## Mock data that is already there

`manage.py seed-showcase` created 10 fictional pilots (some verified, some waiting for documents), 4 pending requests, approved and rejected permits, 20 or so past flights with breaches and a recall, and 3 notices (one active, one scheduled, one cancelled). The Insights tab and the officer queues are therefore not empty.

## If something fails

| Problem | Do this |
|---|---|
| Model answer is slow | The verdict is already on screen. Say "the explanation fills in when the model answers". |
| Phone cannot open the QR link | Fly with the keyboard: W A S D, Q E, R F. |
| Wi-Fi blocks phones | Use a phone hotspot for both laptop and phone. |
| Display shows no flights | Run `prepare-demo` again. |

## Questions judges may ask

- Why MongoDB? One database for geo, text search, vector search, time series, files, TTL and transactions.
- Is the LLM deciding if a flight is allowed? No. Code decides, the model explains.
- Is the rule text real? No, it is a clearly marked sample paraphrase. Loading the real regulation is the next step and the retrieval numbers must be re-run then.
- What is not done? See `docs/RUBRIC_COVERAGE.md`.
