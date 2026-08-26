# WAQAS — VIDEO PIPELINE SETUP
Everything below is copy-paste. ~90 minutes total.
Send Filip a WhatsApp message after each numbered part.

---

## PART 1 — CDN for video hosting (15 min)

Every video platform pulls the MP4 from a public URL. We need one.

**1a. DNS** — Namecheap → getnexalead.online → Advanced DNS → ADD NEW RECORD:
```
Type: A Record | Host: cdn | Value: [same server IP] | TTL: Automatic
```

**1b. SSH in from PowerShell** (`ssh root@SERVER_IP`), then paste:

```bash
mkdir -p /opt/n8n/videos/raw
cat >> /opt/n8n/Caddyfile << 'EOF'

cdn.getnexalead.online {
  root * /srv/videos
  file_server browse
  header Access-Control-Allow-Origin *
  header Cache-Control "public, max-age=31536000"
}
EOF
```

**1c.** Add the volume to the **caddy** service in `/opt/n8n/docker-compose.yml`:
```yaml
    volumes:
      - caddy_data:/data
      - ./Caddyfile:/etc/caddy/Caddyfile
      - ./videos:/srv/videos          # <-- add this line
```

```bash
cd /opt/n8n && docker compose up -d --force-recreate
```

**1d. Verify:** put any file in `/opt/n8n/videos/` and open
`https://cdn.getnexalead.online/` — you should see it listed.

---

## PART 2 — Install vidkit on the server (10 min)

```bash
cd /opt
git clone https://github.com/FILIP_GITHUB_USER/vidkit
cd vidkit
FULL=1 bash bin/install.sh
vidkit --selftest
```

Expect `=== ALL TESTS PASSED ===`. Screenshot it to Filip.

> If `FULL=1` runs out of disk, re-run without it (`bash bin/install.sh`).
> Rendering still works; it just skips local TTS/captions since GitHub
> Actions handles those anyway.

---

## PART 3 — GitHub repo + secrets (20 min)

**3a.** Push this folder to a **new GitHub repo named `vidkit`** under Filip's
account. Make it **public** (public repos get unlimited free Actions minutes).

**3b.** Cloudflare R2 (free tier, no card needed for 10GB):
1. dash.cloudflare.com → R2 → Create bucket → name it `nexalead-video`
2. Settings → Public access → connect a custom domain **or** enable the
   r2.dev public URL — save whichever URL it gives you
3. R2 → Manage API Tokens → Create token → Object Read & Write
4. Save: Access Key ID, Secret Access Key, and the Account ID from the R2 page

**3c.** In the repo → Settings → Secrets and variables → Actions → New secret.
Add all five:

| Name | Value |
|---|---|
| `R2_ACCOUNT_ID` | from 3b step 4 |
| `R2_ACCESS_KEY_ID` | from 3b step 3 |
| `R2_SECRET_ACCESS_KEY` | from 3b step 3 |
| `R2_BUCKET` | `nexalead-video` |
| `R2_PUBLIC_BASE` | the public URL from 3b step 2 |

**3d.** GitHub PAT for n8n: github.com/settings/tokens → Generate new token
(classic) → scope **repo** → copy it. Send to Filip.

---

## PART 4 — n8n wiring (20 min)

**4a.** Import both workflow files:
- `nexalead-render-pipeline.json`
- `nexalead-video-autopilot-v1.json`

**4b.** Add a credential: **Header Auth**, name it `GitHub Bearer`
- Header Name: `Authorization`
- Header Value: `Bearer ghp_xxxxx` (the PAT from 3d)

**4c.** Add env vars — SSH in, edit `/opt/n8n/docker-compose.yml`, under the
n8n service `environment:` block add:

```yaml
      - GITHUB_USERNAME=FILIP_GITHUB_USER
      - N8N_RENDER_CALLBACK=https://n8n.getnexalead.online/webhook/vidkit-render-complete
      - R2_PUBLIC_BASE=https://YOUR_R2_PUBLIC_URL
      - TELEGRAM_BOT_TOKEN=xxxxx
      - TELEGRAM_CHANNEL_ID=@nexalead
      - MASTODON_INSTANCE=mastodon.social
      - BLUESKY_DID=did:plc:xxxxx
      - TUMBLR_BLOG_NAME=nexalead
```

```bash
cd /opt/n8n && docker compose up -d --force-recreate
```

**4d.** In each workflow, open every node with a red ⚠️ and select the matching
credential. **Ignore** red on TikTok, IG Reels, Facebook, Pinterest — those are
blocked pending other tasks and don't stop anything.

**4e.** YouTube: the Google credential needs the YouTube scope added.
console.cloud.google.com → APIs & Services → Library → enable **YouTube Data
API v3** → then in n8n create a **YouTube OAuth2** credential using the same
Client ID/Secret and authorize.

---

## PART 5 — Add sheet tabs (5 min)

Open the Nexalead Google Sheet → File → Import → Upload
`nexalead-video-calendar.xlsx` → choose **"Insert new sheet(s)"**.

Adds 4 tabs: VideoCalendar, HowItWorks, PlatformKeys, HookLibrary.
Don't touch the existing MasterCalendar tab.

---

## NOTE — footage is now OPTIONAL

Filip does not need to record anything for video #1. Rows in VideoCalendar
with a `video_brief` and no `raw_url` are auto-generated from data by
`datavid.py`. The pipeline picks the template itself.

That means the video system can go live the moment Parts 1–5 are done.

---

## PART 6 — Start the TikTok audit (15 min) — DO THIS FIRST, IT WAITS

developers.tiktok.com → your app → **Content Posting API** → request
**Direct Post** → submit for audit.

Until this passes, every automated TikTok post is forced to private/self-only
and cannot be made public retroactively. Takes 2–4 weeks. Starting it today
costs nothing and saves a month later.

---

## NOTE ON RENDER FLAGS

For screen recordings always use screencast mode, otherwise the UI text is too
small to read on a phone:

```bash
vidkit --input raw.mp4 --out short.mp4 --fit screencast \
       --focus 0.6,0.5 --punch 2.1 --autoedit \
       --move dolly_in --grade clean --bloom 0.25 \\
       --hook "..." --script "..."
```

Preview camera looks without any footage:
`python3 bin/cinema.py --demo test.mp4 --move crash_zoom --grade noir`

The render pipeline already passes these automatically. This is only for
manual test renders.

---

## PART 7 — Preflight before activating anything (2 min)

```bash
cd /opt/vidkit && python3 bin/doctor.py --fix
```

Fix every red ✗. Yellow ! is optional. Screenshot the summary line to Filip.

---

## DONE CHECKLIST
- [ ] `https://cdn.getnexalead.online/` lists files
- [ ] `vidkit --selftest` prints ALL TESTS PASSED
- [ ] vidkit repo public on GitHub with 5 R2 secrets
- [ ] Both workflows imported, credentials attached
- [ ] 4 new tabs in the sheet
- [ ] TikTok audit submitted
- [ ] `doctor.py` shows 0 failures

Tell Filip when all six are ticked. He records video #1 and runs the first
real render.

**Blocked on anything for more than 15 minutes → screenshot, skip it, move to
the next item.** Nothing here is sequential except Part 1 before Part 4.
