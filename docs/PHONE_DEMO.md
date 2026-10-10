# Phone demo: fly the simulated drone from a phone, on a big satellite screen

For presentations. The laptop on the projector shows a full-screen satellite view that follows the drone. A phone scans a QR code and becomes the controller, with two touch sticks. Hand the phone to a reviewer and let them try to break the rules: the system reacts live.

## Set up (10 minutes before)

1. Put the laptop and the phone on the same network. A phone hotspot is the safest at a venue. The server listens on the network while it runs, so anyone on that network could open the app. Use your own hotspot, not an open Wi-Fi.
2. Start the app: `./run.sh`. If macOS asks whether Python may accept incoming connections, allow it.
3. Get the demo ready: `python backend/manage.py prepare-demo`. It prints the demo pilot's email and a new password, and creates two approved flights valid for six hours:
   - a permit flight inside a yellow zone (the Secretariat area), with a 60 m height limit and a dashed permit area
   - a free flight in open air, about 1.5 km outside a military zone
4. On the presentation laptop open http://localhost:8000/display.html and sign in as the demo pilot. Press Full screen.
5. Press Take off with phone control on a flight. The QR code appears bottom left.
6. Scan it with the phone camera. The phone opens the controller, no sign-in. The link works for this one flight for 45 minutes.

If you have no phone, the laptop keyboard flies too: W A S D move, Q E turn, R F up and down.

## What the controls do

| Control | Does |
|---|---|
| Left stick, up and down | Climb and descend |
| Left stick, left and right | Turn the drone |
| Right stick | Move forward, back, left, right |
| Let go | The drone hovers |
| Return home | The drone flies itself back and lands. Sticks are off |
| Land now | Lands where it is |

The phone vibrates (Android) and turns red when the drone breaks a rule.

## A three minute script

1. The big screen shows the satellite view, the dashed permit area and the QR code. Say: a pilot got permission for this one place, up to 60 metres. Scan the QR, "my phone is now the remote control".
2. Fly around inside the dashed circle. Banner: ALL CLEAR.
3. Climb. At 54 m the banner turns amber: near the altitude limit. At 60 m it turns red: BREACH, the event log records it, the pilot is alerted. "The permit said 60 metres, the system watched."
4. Come back down: clear again. Now fly out of the dashed circle: BREACH again, because the permit covers only that area of a yellow zone.
5. Open an officer view on another screen (sign in as the admin, Authority page, Live tab). The flight is in the air list. Press Recall. The drone turns for home by itself, the phone says "Returning home, sticks are off", the pilot is alerted. "The officer can call any drone home."
6. Fly the second (free) flight: fly toward the military zone. The screen warns "restricted area ahead" before the edge, then BREACH inside it.
7. Hand the phone to a reviewer. "Try to fly it somewhere you should not."

## If something goes wrong

| Problem | Fix |
|---|---|
| Phone cannot open the link | Same network? Some venue Wi-Fi blocks devices from talking to each other, switch to a hotspot. Check the laptop firewall allowed Python |
| QR shows an old link | Press Fly again on the big screen, the QR is made fresh |
| "Link expired" on the phone | The token lasts 45 minutes. Scan the new QR |
| Flights list is empty | Run `python backend/manage.py prepare-demo` again |
| Drone does not move | The phone must be in Return home mode or the flight recalled: sticks are off then. Take off again |
| No phone at all | Use the keyboard on the laptop |

## What is real and what is simulated

The drone is simulated (movement with wind and GPS noise). The rules are real: the zones, the permit area and height limit, the geofence checks, the alerts, the officer recall and the flight log all run exactly as they would for a real drone. The satellite imagery is Esri World Imagery, credited on screen, fine for a demo.
