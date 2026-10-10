# Guard alerts: a siren on every device in a protected area

## What it does

An official declares an area (for example a campus) as a notice, which is a red zone with a time window. People inside the area open `http://<server>/guard.html` on a phone or laptop on the same Wi-Fi and tap "Turn alerts on" once. When a drone enters the area, every device that has the page open plays a siren, vibrates and turns red.

Path of an alert: the drone enters the notice, the geofence records a breach in MongoDB, a change stream picks it up, the public stream `GET /guard/stream` sends only the area name, the kind and the time (never the pilot, flight or drone) to every open guard page.

## How to use it

1. Officer console, Publish tab: click the campus on the map, set the radius, publish.
2. Officer console, Notices tab: the guard link and a QR code are there. "Sound a test siren now" sets off every listening device and is written to the audit log.
3. On each device: open the link (or scan the QR), pick the area, tap "Turn alerts on".

## Drill (test it with your own phone)

Draw the real boundary first: Publish tab, "Draw the boundary", click the corners of the campus on the satellite map in order, then publish. For the drill, tick "Use the boundary I drew". A circle is only an approximation of a campus.

Officer console, Notices tab, "Drill": type the area name, press "Use my location" (works when the page is opened as localhost on a laptop; otherwise type latitude and longitude), press "Start the drill". The area is declared as a restriction and one simulated drone starts about 600 m away and flies at it, arriving in under a minute. Every device with the guard page open sounds. "End the drill" cancels the restriction and removes the drone.

## Warning before entry

When the geofence look-ahead sees a drone heading into a declared area, the guard devices get a softer first signal: three short beeps, a short vibration and an amber line. It is sent once every 20 seconds per drone and area, and only for declared areas, not for ordinary restricted zones. The red screen and the siren come on entry.

## Notifications when the page is closed (Web Push)

On the guard page, "Also notify me when this page is closed" subscribes the browser to push notifications. The server signs each push with its own key (generated once, kept in the git-ignored `data/.secrets.json`) and sends one for an entry, an approach and a test. Only the area name and the kind are in the message.

Try it on the laptop: open `http://localhost:8000/guard.html` in Chrome, press the button, choose Allow, then close the tab and press "Sound a test siren now" in the officer console. A notification appears.

Browsers only allow push on HTTPS or on localhost. A phone that opens `http://192.168...` (the laptop's address) gets the siren while the page is open, and a clear message instead of push. Phones get push only behind an https address (not set up here). On iPhone, push also needs the page added to the Home Screen.

What was tested: the signing and encryption by the real sender code against a local stand-in for the push service, the stored subscriptions, which areas get which alert, and dead subscriptions being removed. What was not: a full subscribe and delivery in a real browser, because automated Chrome refuses the notification permission.

## Honest limits

- A web page cannot make a device beep without the person opening it once. The browser blocks sound until a tap, and a closed or locked page cannot receive anything. The page asks for a screen wake lock, so a phone that is kept awake and left open works.
- It reaches devices that can reach the server. It does not push to every phone that merely joins the Wi-Fi. To get close to that, the Wi-Fi router can send a first-time visitor to this page (a captive portal page), which is a network setting and not part of this code.
- Push to a closed phone needs an https address for that phone. The code is there (see above), the https address is not.
- Detection of a real drone needs a tracker feeding breaches (Remote ID receiver, radar). Here the breach comes from the simulator. The alert path after the breach is real.
