# SkyClear API contract

Frontend and backend both follow this. Frontend can build against the mock response below before the real backend exists.

## POST /check

Request:

```json
{
  "lat": 12.9500,
  "lng": 77.6680,
  "drone_id": "small-1800",
  "datetime": "2026-10-12T17:00:00+05:30"
}
```

Response:

```json
{
  "verdict": "permission_needed",
  "summary": "Short plain-language explanation, 2 to 3 sentences.",
  "zones": [
    {
      "zone_id": "Z-001",
      "name": "Sample Airport",
      "zone_type": "airport",
      "distance_km": 3.2,
      "geometry": { "type": "Polygon", "coordinates": [[[77.60, 12.95], [77.62, 12.95], [77.62, 12.97], [77.60, 12.97], [77.60, 12.95]]] }
    }
  ],
  "notices": [
    {
      "notice_id": "N-001",
      "title": "Sample VIP movement",
      "starts_at": "2026-10-12T16:00:00+05:30",
      "ends_at": "2026-10-12T20:00:00+05:30",
      "geometry": { "type": "Polygon", "coordinates": [[[77.58, 12.97], [77.60, 12.97], [77.60, 12.99], [77.58, 12.99], [77.58, 12.97]]] }
    }
  ],
  "citations": [
    {
      "rule_id": "R-012",
      "text": "Full text of the rule passage that was used.",
      "source": "Sample source (verify against official regulation)"
    }
  ],
  "explained_by": "template",
  "next_steps": ["Apply for permission on the official portal."],
  "data_last_updated": "2026-10-10",
  "disclaimer": "Decision support only, not legal permission."
}
```

`explained_by` is `llm` when the summary came from the language model and passed the checks, otherwise `template`. The rules that decided the verdict are always in `citations`.

`verdict` is one of: `can_fly`, `permission_needed`, `prohibited`, `cannot_determine`.

`can_fly` is shown in the UI as "No restriction found in our data". Never show "safe".

## GET /zones

Returns all zones as a GeoJSON FeatureCollection for drawing on the map. Each feature has `properties: { zone_id, name, zone_type, rule_ids }`.

## GET /drones

Returns a list of `{ drone_id, name, weight_g, class }` for the dropdown.

## POST /simulate/route

Simulated flight. The backend samples the route about every 100 m and runs the same checks as `/check` at each sample, with time moving forward at the drone speed.

Request: `{ "drone_id": "small-1800", "speed_mps": 10, "datetime": "2026-10-12T10:00:00+05:30", "waypoints": [{ "lat": 12.90, "lng": 77.668 }, { "lat": 13.00, "lng": 77.668 }] }`

Response: `{ "drone": {...}, "samples": [{ "lat", "lng", "dist_m", "t_s", "verdict", "zones": ["name"], "rule_ids": ["R-001"] }], "summary": { "worst_verdict", "first_issue": { "verdict", "dist_m", "t_s", "zones", "rule_ids" } or null, "length_m", "duration_s" }, "data_last_updated", "disclaimer" }`

## Authentication (built)

Signed-in calls send `Authorization: Bearer <access_token>`. The access token is a JWT valid for 15 minutes. When it expires the API answers 401 `{ "detail": "token_expired" }`, and the client calls `/auth/refresh` once and retries. Roles: `pilot`, `official`, `admin` (an official with no office). Checking (`/check`, `/simulate/route`, `/zones`, `/drones`, `/notices/active`, `/config`, `/examples`) needs no sign-in. There are no built-in accounts: the first admin comes from `manage.py create-admin`, officials are invited by the admin.

One-time codes are sent to the account's email (`OTP_CHANNEL=email`) or mobile number (`sms`) by the provider in `.env` (`smtp`, `twilio`, or `console` for the server log). The API never returns a code unless `OTP_DEV_ECHO=1`, which is for tests only.

| Endpoint | Purpose |
|---|---|
| POST /auth/register | `name, email, phone, password`. Phone is a 10-digit Indian mobile. Sends a code. Returns `{ needs_otp, identifier (the email), sent_to (masked) }` |
| POST /auth/otp/verify | `identifier` (email or phone), `code`. Confirms the account and returns tokens. Also the second half of code login |
| POST /auth/otp/request | `identifier`. Always answers `{ sent: true }`, so it cannot be used to find out who has an account |
| POST /auth/login | `identifier` (email or phone), `password`. Returns tokens, or 403 `not_verified`, or 423 when locked after 5 wrong passwords. Officials get `{ mfa_required }` or `{ mfa_setup_required }` with an `mfa_token` when authenticator codes are on |
| POST /auth/password/forgot, POST /auth/password/reset | Send a reset code (same answer for unknown accounts), then `identifier, code, new_password`. Signs out every other session |
| POST /auth/password/change | Signed in: `current_password, new_password`. Clears the "must change password" flag of an invited official |
| POST /auth/totp/setup, POST /auth/totp/verify | Enrol and use an authenticator app. `REQUIRE_OFFICIAL_MFA=1` makes it mandatory for officials |
| POST /auth/refresh | `refresh_token`. Returns a new pair and the old refresh token stops working. Reusing an old one ends the whole session |
| POST /auth/logout | `refresh_token`. Ends the session |
| GET /me | Current user (phone is masked) |
| GET, POST /admin/officials | Admin only. Invite: `name, email, authority_id`. Returns a one-time `temporary_password` the admin hands over. The official must change it at first sign-in |

Tokens object: `{ access_token, refresh_token, token (same as access_token), expires_in, user }`. Passwords are stored with argon2id. Auth endpoints are rate limited per address and per identifier.

## Config for the front end (built)

`GET /config.js` sets `window.SKYCLEAR` (city, map centre, zoom, search area, drone classes, code channel) and is loaded before the app code. `GET /config` returns the same as JSON. `GET /examples` returns real spots built from the zones in the database and an example route. The place comes from `data/region.json`.

## Permits, routing and verification (built)

| Endpoint | Role | Purpose |
|---|---|---|
| GET /authorities | any | Authorities with name, type, office and response time |
| GET /route-preview?lat=&lng= | pilot | Who would review a permission request here (`routed_to`), or 422 `no_authority_for_area` |
| POST /flights (kind permission) | pilot | Needs a verified pilot and drone (403 otherwise). Returns `routed_to`, `authority_id` |
| GET /flights | any | Officials see only their authority's requests. Overdue ones escalate to the parent. Each flight has `overdue` and `permit` |
| POST /flights/{id}/decision | official | Approve with `alt_max_m` and `conditions` to issue a signed permit, or reject with a reason. 403 if routed elsewhere |
| POST /flights/{id}/preflight | pilot | Re-checks permit, window, serial, verification, new notices. Returns `cleared`, `reasons`, `cleared_until` |
| GET /permits/{id} | owner or official | Permit with `status` and `signature_ok` |
| POST /permits/{id}/revoke | official | Reason required. Alerts the pilot, the next preflight fails |
| POST /notices | official | Response also has `conflicting_permits` |
| POST /uploads, GET /uploads/{id} | signed in | JPG, PNG or PDF up to 5 MB. Owner and officials can read |
| POST /me/verification/pilot, POST /me/drones/{id}/verification | pilot | Send certificate or serial plus documents for review. Duplicate certificate or serial returns 409 |
| GET /verification/queue, POST /verification/{id}/decision | official | Verify or reject. The badge shows who and when |


## Ask SkyClear (built)

`POST /ask` with `{ "question": "...", "lat", "lng", "drone_id", "datetime" }` (the last four are optional and add a spot). No sign-in needed, rate limited. The answer comes only from the rule passages: MongoDB search finds them (Atlas Search, plus vector search when embeddings exist), and if the LLM is on it words the answer, otherwise the answer is taken straight from the passages. With a spot, the verdict decided by the rule engine is included and the rules that decided it come first, so the answer cannot disagree with `/check`.

Response: `{ answer, citations: [{ rule_id, text, source, score }], spot: { verdict, zones, notices, rule_ids, drone, summary } or null, retrieval, answered_by: "llm" | "extracted" | "none", disclaimer }`. When nothing in the rules matches the question, `answered_by` is `none`, `citations` is empty and the answer says it could not find it. An LLM answer is used only if every citation id is real and it does not contradict the decided verdict.
