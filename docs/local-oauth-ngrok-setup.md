# Local Dev Login Setup (Google OAuth via your own ngrok tunnel)

This guide gets Google sign-in working when running GitGrit locally.

**Why ngrok?** GitGrit's Google OAuth client only accepts sign-in redirects
that come back to an exact, pre-registered URL. `http://localhost:8000` is not
registered (and Google is picky about it), so we route the app through a stable
public URL provided by ngrok. You'll set up **your own** tunnel — the one in the
shared `.env` belongs to someone else's machine and won't work for you.

---

## 1. Install and authenticate ngrok

1. Create a free account at https://ngrok.com and sign in.
2. Install ngrok:
   - macOS: `brew install ngrok`
   - Linux: see https://ngrok.com/download
3. Connect your account (copy the token from the ngrok dashboard → *Your Authtoken*):
   ```bash
   ngrok config add-authtoken <YOUR_AUTHTOKEN>
   ```

## 2. Claim your free static domain

The free tier includes **one** permanent domain — use it so your URL doesn't
change every restart.

1. In the ngrok dashboard go to **Universal Gateway → Domains**.
2. Copy your assigned domain. It looks like:
   ```
   your-unique-name.ngrok-free.dev
   ```
   Keep this handy — you'll use it in steps 3, 4, and 5. Below it's written as
   `YOUR-DOMAIN.ngrok-free.dev`.

## 3. Point your `.env` at your domain

Open `.env` in the project root and set `SITE_URL` to your domain (note: **https**,
no trailing slash):

```env
SITE_URL=https://YOUR-DOMAIN.ngrok-free.dev
```

This is what makes the app send the correct redirect URL to Google, and it also
configures `ALLOWED_HOSTS` and CSRF for your tunnel automatically. Leave
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` as they are — those are shared.

## 4. Register your callback in Google Cloud (one-time)

Google must be told to trust your domain's callback. The OAuth client lives in
the Google Cloud project **number `66239560547`**, client ID ending **`…aj66`**.

If you have access to that project:
1. Google Cloud Console → switch to project `66239560547`.
2. **APIs & Services → Credentials →** open the OAuth 2.0 Client ID ending `…aj66`.
3. Under **Authorized redirect URIs**, click **Add URI** and paste — exactly:
   ```
   https://YOUR-DOMAIN.ngrok-free.dev/accounts/google/login/callback/
   ```
   (https, your domain, and the trailing slash all matter.)
4. **Save.** Changes can take a few minutes to take effect.

If you don't have access to that project, send the URI above to whoever owns the
Google Cloud project and ask them to add it.

## 5. Run it

Open two terminals in the project root.

**Terminal 1 — start the app stack:**
```bash
docker compose up -d                 # database
uv sync                              # dependencies
uv run python manage.py migrate      # migrations
uv run python manage.py runserver    # serves on localhost:8000
```

**Terminal 2 — start your tunnel (forwards your public domain to the local server):**
```bash
ngrok http 8000 --domain=YOUR-DOMAIN.ngrok-free.dev
```

## 6. Sign in

Open **`https://YOUR-DOMAIN.ngrok-free.dev`** in your browser (use the ngrok URL,
**not** `localhost:8000` — logging in via localhost will fail). Click
**Sign in with Google** and you should be through.

---

## Troubleshooting

- **`Error 400: redirect_uri_mismatch`** — the URI in Google doesn't match what
  the app sent. Click "see error details" on Google's page; it shows the exact
  `redirect_uri`. It must match step 4 character-for-character (https, domain,
  trailing slash). Also confirm `SITE_URL` in `.env` matches your domain and that
  you restarted `runserver` after editing `.env`.
- **`DisallowedHost` / 400 from Django** — `SITE_URL` doesn't match the domain
  you're visiting. Fix `.env` and restart the server.
- **ngrok shows the app but login still hits localhost** — make sure you opened
  the `https://…ngrok-free.dev` URL, not `localhost:8000`.
- **Server changes to `.env` not taking effect** — stop and restart
  `runserver`; it reads `.env` at startup.
