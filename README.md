# SkyClear: explainable drone flight check

Track 2: RAG Engine (MongoDB hackathon)

## Problem statement

Before every flight, a drone pilot must answer one question: "Can I fly here, today, with this drone?"

The answer depends on several things at once:
- the drone's weight class
- nearby airports and sensitive areas
- the date and time of the flight
- temporary restrictions such as VIP movements, rallies and events
- the current drone regulations

This information is spread across regulation PDFs, zone maps and local notices. Existing tools mostly show a zone color without explaining which rule applies to the pilot's drone, and they do not combine rules with time-based notices. A wrong decision can mean fines, a confiscated drone or a safety incident.

## Idea

A web app where a pilot:
1. clicks a location on a map,
2. chooses a drone model, date and time,
3. gets one of four verdicts:
   - Can fly (no restriction found in our data)
   - Permission needed
   - Prohibited
   - Can't determine (with who to ask)

The app shows the relevant zones on the map and the exact rule passages behind the verdict, so the pilot can check the source. It never says "safe". It says "no restriction found in our data".

SkyClear is a pre-flight planning tool. It does not control or connect to a drone in this version.

## How it works

```
Map click + drone + date/time
   -> 1. Geo search: zones and active notices near the point (MongoDB geospatial)
   -> 2. Rule search: relevant rule passages (MongoDB vector + keyword search, metadata filters)
   -> 3. Rule engine: Python code decides the verdict
   -> 4. LLM (Ollama): explains the verdict and picks citations from the retrieved passages
   -> Response: verdict, zones for the map, citations, "data last updated"
```

Key design choice: code decides the verdict, the LLM only explains and cites. Citation IDs returned by the LLM are checked against the retrieved passages, and unknown IDs are dropped.

## Data (MongoDB collections)

| Collection | Contents |
|---|---|
| rules | rule_id, text, embedding, zone_type, drone_classes, effective_from, source |
| zones | zone_id, name, zone_type, geometry (GeoJSON), rule_ids, source |
| drones | drone_id, name, weight_g, class |
| notices | notice_id, text, area (GeoJSON), starts_at, ends_at, source |
| eval_cases | input, expected_verdict, expected_rule_ids |

Indexes: 2dsphere on zones.geometry and notices.area, a vector index on rules.embedding (768 dimensions for nomic-embed-text), a text index on rules.text.

Data caveats:
- Rule text is placeholder paraphrase and must be verified against the official regulation before the demo.
- Zones are built from open data (OurAirports, OpenStreetMap) and labeled as derived.
- Notices are sample data and are labeled as such.

## Prototype scope

Two parts: real airport zones for India on the map (built by `backend/build_zones.py` from OurAirports), and a simulated drone. In the "Simulate flight" tab the pilot clicks waypoints, the backend checks the route every 100 m with the same engine as a single check (`POST /simulate/route`), and the drone flies the route on the map with a live verdict and a summary of the first issue.

## Tech stack (all free / open source)

- MongoDB (Docker, or free Atlas) for storage, geo search, vector search and hybrid search
- Ollama with qwen2.5 (LLM) and nomic-embed-text (embeddings)
- FastAPI backend
- Leaflet + OpenStreetMap frontend

## Evaluation

About 20 test scenarios with known correct answers, stored in eval_cases. Metrics:
- verdict accuracy
- retrieval recall@k (did the expected rule appear?)
- false-safe rate (how often we said "can fly" when we should not have)
- vector-only vs hybrid search comparison

Numbers in the presentation must come from real runs of this evaluation.

## Out of scope for the hackathon

A real drone connection (a simulated drone is in scope), multi-agent loops, user accounts, flight-plan upload. The roadmap is route upload, change-stream alerts for new notices, and live telemetry from open-source autopilots (MAVLink, tested on a simulator first).

## Design rules

See [DESIGN_RULES.md](DESIGN_RULES.md). Run `./scripts/check_design.sh` before every commit.

## Disclaimer

Decision support only, not legal permission. Always confirm with the official portal and local authorities.

## Running it on the shared laptop

Server laptop runs Ollama and MongoDB. Other laptops point to it:

```
# on the server laptop
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull qwen2.5:7b        # use qwen2.5:3b if RAM is 8 GB
ollama pull nomic-embed-text
ipconfig getifaddr en0         # find the server IP

# on other laptops
export OLLAMA_URL=http://<server-ip>:11434
export MONGO_URI=mongodb://<server-ip>:27017
```

If the venue Wi-Fi blocks laptop-to-laptop traffic, use a phone hotspot.

## Folder layout

```
data/       rules.json, zones.geojson, drones.json, notices.json, eval_cases.json
backend/    config.py, geo.py, build_zones.py, sim.py, search.py, verdict.py, explain.py, main.py, load_data.py, eval.py, tests/
frontend/   index.html, terms.html, privacy.html
scripts/    check_design.sh
```

## Status

- [x] Folder structure, drones.json, requirements.txt
- [x] Design rules (CLAUDE.md, DESIGN_RULES.md, scripts/check_design.sh), skeleton loader, Terms and Privacy pages
- [x] Base: sample data, local search, rule engine, template explanation, API, map page, tests (runs without MongoDB or Ollama)
- [x] Airport zones for India (derived, 5 km / 3 km circles), simulated drone route check and playback
- [ ] Real rules and notices, military and park zones
- [ ] load_data.py and MongoStore (geo, vector, hybrid search, embeddings)
- [ ] LLM explanation and citation validation
- [ ] 20 eval cases and metrics
- [ ] Demo rehearsal

Who does what: see [TEAM.md](TEAM.md).
