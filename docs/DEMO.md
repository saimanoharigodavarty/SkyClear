# Demo script

About 9 minutes. Every step maps to one of the six judging components. Do the setup once, before the judges arrive.

## Setup (15 minutes before)

1. Docker running, then `./run.sh` in the project folder.
2. `cd backend && ../.venv/bin/python manage.py prepare-demo` makes two flights that are ready to fly for the next 6 hours and prints the demo pilot's password.
3. Run `.venv/bin/python scripts/demo_check.py`. Every line must say PASS. It tells you the fix for each FAIL, and prints the two links you need.
4. Presentation computer: sign in as the demo pilot, open `/display.html` full screen.
5. Second window or second laptop: officer console, signed in as the administrator.
6. Your phone and one teammate's phone: same Wi-Fi (or a phone hotspot for everything). Open the guard link, choose "Every declared area", tap "Turn alerts on", volume up.
7. In the officer console, Notices tab, press "Sound a test siren now". Both phones must go red and sound. If not, fix this first.
8. Draw the real campus as a boundary: Publish tab, "Draw the boundary", click the corners, publish with an end time several hours ahead.

Logins are in `data/demo_credentials.txt` (not in git). Do not read passwords out loud.

## The story, in order

| Min | What you do | What you say | Component |
|---|---|---|---|
| 0:00 | Pilot map: click a green spot, then a red zone | "A pilot asks: can I fly here? Code decides from MongoDB geo data. The AI only explains and cites the rule." | Technology stack |
| 1:00 | Same check: rule cards, the sentence the AI writes | "Hybrid retrieval: Atlas Search plus Atlas Vector Search, fused inside MongoDB with $rankFusion. If the model is off, the plain explanation still works." | AI/ML |
| 1:45 | Ask tab: "Do I need permission near an airport?", then "best pizza" | "The rules appear at once, the AI wording fills in after. A relevance gate refuses what the rules do not cover. Citations are checked." | AI/ML |
| 2:30 | Request permission in a yellow zone as the demo pilot | "The request is routed to the right office by zone type and distance." | Backend and API |
| 3:00 | Officer, Requests: approve with conditions. Pilot window shows the permit with no reload | "One MongoDB transaction writes the permit, the flight, the alert and the audit entry. It reached the pilot through a change stream." | MongoDB |
| 3:45 | Display screen: take off. Show chase view, then drone view with the map beside it | "A modelled drone in 3D. Drone view shows the distance to the nearest zone and the time to reach it. The map beside it shows where it is." | Advanced |
| 4:30 | Fly out of the permit area or over the height limit (keyboard or phone) | "Permit-aware geofence. Inside the permit a yellow zone is fine, outside it is a breach. The screen sounds a siren." | Advanced, Security |
| 5:15 | Officer Live tab: breach appears, press Recall | "The officer sees it at once and recalls. The drone returns home by itself. The pilot is told why." | Backend and API |
| 6:00 | Officer, Notices tab: "Start the drill" with "Use the boundary I drew". Watch the guard phones | "The area is declared on the real campus boundary. A drone flies at it. First a warning beep on every device in the area, then the siren and a red screen on entry. Only the area name and the time are sent, never who is flying." | MongoDB, Security |
| 7:15 | End the drill. Insights tab | "Aggregations materialised with $merge, an append-only audit log, change stream status." | MongoDB |
| 8:00 | Show `docs/RESULTS.md` and `docs/RUBRIC_COVERAGE.md` | "Numbers come from runs, with the machine named. The coverage table lists what is not done." | Performance |

## Who does what (with three people)

- Presenter: speaks and drives the pilot screen.
- Second person: officer console, publishes, approves, recalls, starts the drill.
- Third person: holds the guard phone up so the judges see and hear it.

## What is real and what is simulated, say it first

"The drone is simulated. The alert path after a breach is real: MongoDB, change stream, the officer feed and the guard devices. A real Remote ID receiver or radar can feed the same path through `POST /ingest/position`, tested with a script."

## If something fails

| Problem | Do this |
|---|---|
| Model answer is slow | The verdict and the rules are already on screen. Say the explanation fills in when the model answers. |
| Phone cannot open the guard or controller link | Use a phone hotspot for laptop and phones. Fly with the keyboard: W A S D, Q E, R F. |
| A guard phone does not sound | Silent switch on, volume down, or "Turn alerts on" was not tapped. Press "Sound a test siren now" to find out. |
| Display shows no flights | Run `prepare-demo` again. |
| Drill drone never arrives | End the drill and start it again. Check the guard page says Listening. |
| Everything is red on `demo_check.py` | Docker is not running. Start it, run `./run.sh`. |

## Do not say

- "It detects real drones." It detects the simulated drone and anything a tracker reports.
- "Every phone on the Wi-Fi beeps." People open the guard page once.
- "The rules are official." They are marked sample passages.

## Honest answers to the awkward questions

| Question | Answer |
|---|---|
| Is the drone real? | The drone in the demo is simulated. A real tracker can post positions to `POST /ingest/position` with its own key, and then everything after is the same (geofence, breach in MongoDB, officer feed, guard siren). That path is tested with a script, not with a real receiver. |
| Does every phone on the Wi-Fi beep? | No. A browser needs one tap to allow sound and cannot receive anything when closed. People open the guard page once. A phone app or Web Push is the next step. |
| Can someone fake an alert? | The alert is made only from a breach recorded by the server. A test siren needs an official login and is audited. Tracker positions need a tracker key, which can be revoked. A leaked key can report false positions. |
| Does the guard page leak who is flying? | No. Only the area name, the kind and the time are sent. |
| Is the regulation text real? | No, seven marked sample passages. Retrieval numbers need the real corpus. |
| Where does it slow down? | About 390 checks per second on one process. The zone map and live list queue at 200 users. Numbers and the fix are in `docs/RESULTS.md`. |
| Warning before entering? | Yes. The drone view and the display screen beep as the drone nears an area, and the guard devices get three short beeps first, then the siren on entry. |
