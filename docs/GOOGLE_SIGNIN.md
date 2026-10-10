# Sign in with Google

Optional. Pilots can create an account and sign in with one tap. Without a client ID in `.env` the button is simply not shown, and everything else works.

## Turn it on (about 5 minutes)

1. Open https://console.cloud.google.com and pick or create a project.
2. Set up the consent screen (APIs and Services, OAuth consent screen, or Google Auth Platform, Branding):
   - App name SkyClear, your support email.
   - Audience: External. While the app is in Testing, only the Google accounts you add under Test users can sign in, so add yourself and the people who will try it.
3. Create the client (APIs and Services, Credentials, Create credentials, OAuth client ID):
   - Application type: Web application.
   - Authorized JavaScript origins: `http://localhost:8000`. (No redirect URI is needed for this button.)
4. Copy the Client ID. It ends in `.apps.googleusercontent.com`. There is no secret to copy, SkyClear only verifies the signed token Google hands to the page.
5. Put it in `.env` and restart the app:
   ```
   GOOGLE_CLIENT_ID=1234567890-abcdef.apps.googleusercontent.com
   ```
6. Open http://localhost:8000/account.html. A "Continue with Google" button appears.

## Limits to know

- Google accepts only `https` addresses or `http://localhost` as origins. A network address such as `http://10.0.0.5:8000` is refused, so the Google button works on the laptop at `localhost`. The phone controller does not need it, it pairs by QR code. A real deployment needs an https address.
- The button works at the address you registered. Opening the app at another address (a different port, or the network address) shows the button but Google will refuse.

## What the server checks before it signs anyone in

| Check | Why |
|---|---|
| The token is valid and was made for this app (`aud` equals your client ID) | A token Google made for another site cannot be replayed here |
| Issued by Google (`iss`) | |
| `email_verified` is true | Otherwise someone could claim an email address they do not own |
| The account is a pilot | Officials sign in with a password (and an authenticator when it is on). Google must never be a way around that. An official's email is refused |
| An email already linked to one Google account refuses a different one | |
| An account that was started but never confirmed loses its password when Google proves the email | Stops someone from starting an account with a victim's email and a password they know |

A Google account has no SkyClear password. If the person later wants one, "Forgot your password" sends a code to their email. Signing in with a password for a Google-only account gives a normal error that points to Google, not a crash.
