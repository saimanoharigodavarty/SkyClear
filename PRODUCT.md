# SkyClear product spec

High-level product definition and the list of known loopholes. Read with [README.md](README.md) (the idea and the pipeline) and [API.md](API.md) (the contract).

## One line

A platform where registered drone pilots check a flight, get alerted when something changes, and see the exact rule behind every answer.

## The gap this closes

Today a pilot checks once, flies later, and never hears about a VIP movement, rally or new restriction issued in between. SkyClear keeps watching after the check. The check is the entry point. The alert is the reason to stay.

## Users

| User | Needs |
|---|---|
| Pilot | Check a spot or route, save a planned flight, get alerted if it becomes restricted, see sources |
| Authority or operator | Publish a temporary restriction (VIP movement, event, emergency) and know which registered pilots it reaches |
| Platform admin | Keep rules, zones and notices accurate and current, with an audit trail |

## Accounts and registration

Registration has two layers. They must not be confused in the UI.

1. SkyClear profile: a pilot account and the drones the pilot lists on it. Needed for alerts, saved flights and the flight log.
2. Government registration: the pilot and drone numbers issued by the official regulator. In the prototype the pilot types these in and we show them as "self-declared, not verified". Later we verify against the official registry if an API is available.

Rule: checking a spot stays open to anyone without an account. Alerts, saved flights and logs need an account. Forcing sign-in before the first check would cost us users for no safety gain.

## Core flows

1. Check: pick a spot, drone, time. Get a verdict and cited rules. (built)
2. Simulate: draw a route and watch a simulated flight checked against zones and notices over time. (built)
3. Plan and watch: save a flight (area, time window, drone). SkyClear watches it. (next)
4. Notify: when a new or changed notice touches a watched flight, alert the pilot. (next)
5. Publish: an authority posts a notice, and sees how many watched flights it affects. (next)
6. Log: after the flight window, the plan is stored with the verdict it had and every alert sent. (later)

## Notification design

Triggers:
- A new notice overlaps a saved flight in space and time.
- A notice changes or is cancelled (send the update too, a cancelled VIP movement is good news).
- Rules or zones change for an area with a saved flight.
- Reminder before takeoff: "re-check now", because any earlier verdict can be out of date.

Delivery: in-app inbox and a live banner first (server-sent events), email second. Each alert says what, where, when, the verdict change, and the source. Every alert needs an acknowledge action, and unacknowledged high-severity alerts repeat.

Mechanism: MongoDB change streams on notices. On an insert or update, run a geo and time query against saved flights and create one notification per affected flight.

Demo moment: an admin posts a VIP movement, and a registered pilot with a planned flight there sees the alert appear within seconds.

## Architecture additions

New collections: users, pilots (profile and declared registration numbers), drone_registrations, flight_plans, notifications, audit_log. Notices gain a status (draft, active, cancelled), a publisher and a published time. Roles: pilot, authority, admin.

## Honest limits of the product

- SkyClear is advisory. It cannot stop a drone, and a pilot who ignores it or never registers is invisible to it.
- It is decision support, not legal permission (already in the Terms).
- The prototype uses placeholder rules and derived zones. See the loophole list.

## Loopholes

Severity: High means a wrong or unsafe answer, or harm to a person. Medium means a degraded or misleading experience. Low means polish.

### A. Known bugs in the current code (fix first)

| # | Loophole | Severity | Fix |
|---|---|---|---|
| A1 | FIXED. An active notice with no matching notice rule was ignored, so the verdict could be "can fly" during a VIP movement. Now the notice itself becomes a prohibiting, cited rule. | High | If a notice is active at the point and no rule matches, return prohibited or at least cannot_determine, and cite the notice itself |
| A2 | FIXED. Inside a zone with no matching rule, the function returned cannot_determine immediately and could hide a prohibited result from another zone. Now all hits are collected first. | High | Collect all hits first, then take the worst. Treat "no rule" as cannot_determine only when nothing stricter was found |
| A3 | Route sampling every 100 m can skip a zone or notice narrower than 100 m, such as a motorcade corridor. | High | Sample by geometry intersection (segment against polygon), not by distance steps |
| A4 | "Nearby" distance uses the nearest vertex, so it is wrong for long edges. | Low | Use true point-to-segment distance |
| A5 | Polygon holes are ignored. | Medium | Handle inner rings |
| A6 | A datetime with no timezone is treated as UTC. | Medium | Require an offset or use the zone's local timezone |

### B. Data and rules

| # | Loophole | Severity | Mitigation |
|---|---|---|---|
| B1 | Rule text is placeholder and may be wrong or outdated, leading to a false "can fly". | High | Verify every rule against the official regulation, show source and effective date, mark unverified rules, show a data-age warning |
| B2 | Airport zones are 3 and 5 km circles we derived. Real zones differ by airport and have height bands. | High | Label as derived (done), replace with official airspace data where available |
| B3 | Coverage gaps: no military, border, prison, government building, nuclear, power or state-specific zones. An empty map looks like a clear map. | High | Show a coverage panel listing what the data includes and excludes. Say "no restriction found in our data", never "clear" |
| B4 | No official live feed for VIP movements and rallies. They are often issued at the last minute. | High | Authority publishing channel, manual admin entry, "notices last synced" time on every answer |
| B5 | Altitude, daylight or night, line of sight and purpose are ignored. Real rules depend on them. | High | Add altitude and purpose to the request and to rule conditions |
| B6 | Drone class comes from weight only. Real obligations also depend on category, certificate, insurance and commercial use. | Medium | Model the real categories with the regulation in hand |
| B7 | Overlapping zones with conflicting rules, and which authority wins. | Medium | Explicit precedence per rule, shown to the user |
| B8 | Pilot GPS error and drift near a zone edge. | Medium | Add a safety buffer and warn when within it |

### C. Notifications

| # | Loophole | Severity | Mitigation |
|---|---|---|---|
| C1 | Alert never arrives (phone offline in the field, email filtered, tab closed). | High | Multiple channels, an alert banner on every app open, a mandatory re-check at flight time, and a verdict "valid until" time |
| C2 | A notice is issued minutes before the flight, or after the pilot's last check. | High | Show the time of the last check on the verdict and expire it. Reminder before takeoff |
| C3 | Alert fatigue from false or repeated alerts makes pilots ignore the real one. | Medium | Overlap-based triggers only, dedupe, severity levels, one alert per change |
| C4 | A cancelled or changed notice is not followed up. | Medium | Treat updates and cancellations as first-class alerts |
| C5 | Fake or mistaken notices from an untrusted publisher. | High | Only the authority role can publish, with login, audit log and a cancel path. Admin review in the prototype |
| C6 | VIP movement locations and times are security-sensitive. Publishing them widely can endanger people. | High | Publish only what the authority approves, in the form it approves (area and window, no route details). Show to authenticated pilots first, not the public map |
| C7 | Alert subscriptions reveal where pilots plan to fly. | Medium | Store the minimum, restrict access, allow deletion |

### D. Registration and identity

| # | Loophole | Severity | Mitigation |
|---|---|---|---|
| D1 | Self-declared pilot and drone numbers can be fake. | Medium | Label as self-declared. Verify with the official registry later |
| D2 | Users read "registered on SkyClear" as "legally registered". | High | Plain wording on every screen where it appears, covered in the Terms |
| D3 | Shared or stolen accounts, one account for a whole company. | Medium | One-time code sign-in, organization accounts with named pilots |
| D4 | Mandatory sign-in before a check loses users. | Medium | Guest checks stay open (above) |
| D5 | Unregistered or hostile drones never use the platform. | Info | State the limit honestly. Authority-side tools are a later phase |
| D6 | Personal data law (India's DPDP Act) needs consent, purpose limits and deletion. | High | Consent screen, minimal fields, delete account and data. Legal review before any launch |

### E. Simulation

| # | Loophole | Severity | Mitigation |
|---|---|---|---|
| E1 | The simulated drone can be mistaken for live tracking of a real drone. | Medium | "Simulated flight" on the page (done), never show it as telemetry |
| E2 | A passing simulation is read as approval of the route. | High | Say it is not a flight plan approval. Only the official portal approves |
| E3 | Straight legs ignore terrain, altitude, wind and drift off the route. | Medium | Corridor buffer around the route, altitude input |
| E4 | A future link to a real autopilot (MAVLink) could be spoofed. | Medium | Authenticate telemetry sources. Simulator only until then |

### F. Security and operations

| # | Loophole | Severity | Mitigation |
|---|---|---|---|
| F1 | Notice text goes to the LLM, so a malicious notice can try to steer it (prompt injection). | High | The LLM never decides. Keep the verdict separate from the summary, validate citations (done), strip and cap notice text |
| F2 | The LLM summary can contradict the verdict. | Medium | Show the code verdict badge as the authority. Check the summary for the verdict words |
| F3 | No authentication, rate limits or input limits on the API. | Medium | Auth for publish and account routes, rate limits, size caps on routes and waypoints |
| F4 | MongoDB and Ollama exposed on the venue network without auth. | Medium | Acceptable on a trusted hotspot for the hackathon only. Never for a real deployment |
| F5 | A single laptop is the server. One failure ends the demo. | Medium | Run locally with the JSON store as the fallback (it already works with no database), record a backup demo |
| F6 | Demo numbers that are not from real runs. | High | Only quote numbers from eval.py output (already a project rule) |

## Build order for the hackathon

1. Done: A1 and A2 fixed with tests, accounts, authority notices, saved flights with live alerts, MongoDB, Ollama explanation, 20 eval cases.
2. Next: verify real rule text, real notices source, run the eval against the remote Ollama and record vector vs hybrid numbers.
3. Then: change-stream alerting (alerts are sent when the notice is published today), A3 to A6, demo rehearsal with a backup recording.

Later: official registry verification, email and SMS, authority dashboard, route corridor checks, altitude, flight log, live telemetry from a simulator.
