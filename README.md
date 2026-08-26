# vidkit — screen recording → branded short → 10 platforms, on autopilot

Zero paid dependencies. Runs on CPU. Renders off-box on GitHub's free runners
so your 2GB Hetzner instance never chokes.

```
OBS capture  →  raw_url in sheet  →  AI writes hook + script  →  GitHub Actions
renders (silence-strip, TTS, karaoke captions, brand)  →  R2 public URL
→  n8n video autopilot posts to 10 platforms  →  sheet marked posted
```

---

## What it produces

- 1080×1920, 30fps, H.264, faststart (correct for every short-form platform)
- Three fit modes: `screencast` (punch-in, keeps UI text legible — use this for
  OBS captures), `fill` (blurred backdrop plate, for near-vertical footage),
  `native` (letterbox on brand colour)
- Slow horizontal pan across the action in screencast mode
- Opening hook card in the upper third, on a dark plate, never covering content
- Word-level karaoke captions, active word in brand accent
- Persistent brand tag, closing stat card
- Auto thumbnail + sidecar JSON with duration/size/word count

Two brands built in: `nexalead` (mint `#00E5A0` on near-black) and
`armonia` (gold `#C8B07A` on black).

---

## Install (server)

```bash
git clone https://github.com/YOUR_USER/vidkit && cd vidkit
sudo FULL=1 bash bin/install.sh
```

`FULL=1` also installs Kokoro TTS + faster-whisper (~2GB). Without it you can
still render — pass `--no-tts --no-asr`, or supply captions with `--srt`.

The installer also: creates a 4GB swapfile (**essential** on a 2GB box),
installs Poppins, registers the `vidkit` command, and appends a `cdn.` vhost
to your Caddyfile.

Verify:

```bash
vidkit --selftest      # 20 assertions, renders both brands end to end
```

---

## Use it manually

```bash
vidkit --input raw.mp4 --out short.mp4 \
  --brand nexalead \
  --hook "\$2.14 ran this all week." \
  --script "One sentence in. Twelve platforms out. Total cost, two dollars." \
  --stats "47 posts|12 platforms|\$2.14" \
  --autoedit
```

| Flag | Effect |
|---|---|
| `--autoedit` | Strips every silence first (auto-editor). Biggest single quality win on screencasts. |
| `--script` | Drives both the TTS voiceover and the captions. |
| `--no-tts` | Keep the original audio, no synthetic voice. |
| `--srt file.srt` | Use existing captions instead of transcribing. |
| `--stats "a\|b\|c"` | Closing card, three items. |
| `--music bed.mp3` | Loops a bed at −24dB under the narration. |
| `--no-zoom` | Disable ken-burns (use for footage that already moves). |
| `--fit screencast` | **Use this for every OBS capture.** Punches in so small UI text stays readable on a phone. Without it, 14px node labels become ~8px and nobody can read them. |
| `--focus 0.6,0.5` | Where to punch in, as x,y fractions of the source frame. |
| `--punch 2.1` | Magnification. 1.9–2.3 is the useful range for 1080p captures. |
| `--preset` | `ultrafast` on the Hetzner box, `veryfast` in Actions. |
| `--whisper-model` | `tiny`/`base`/`small`. **Never go above `base` on 2 vCPU.** |

---

## Autopilot wiring

**1. Import both workflows into n8n**
- `nexalead-render-pipeline.json` — watches for `needs_render` rows, writes the
  script with GPT-4o, fires GitHub Actions, catches the completion webhook
- `nexalead-video-autopilot-v1.json` — posts finished videos to 10 platforms

**2. Push this repo to GitHub** as `vidkit`, then add repo secrets:

| Secret | Value |
|---|---|
| `R2_ACCOUNT_ID` | Cloudflare account id |
| `R2_ACCESS_KEY_ID` | R2 API token id |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |
| `R2_BUCKET` | e.g. `nexalead-video` |
| `R2_PUBLIC_BASE` | e.g. `https://cdn.getnexalead.online` |

**3. n8n environment variables**

```
GITHUB_USERNAME=your-github-user
N8N_RENDER_CALLBACK=https://n8n.getnexalead.online/webhook/vidkit-render-complete
R2_PUBLIC_BASE=https://cdn.getnexalead.online
```

**4. GitHub token** — a classic PAT with `repo` scope, added in n8n as
Header Auth: `Authorization` = `Bearer ghp_...`

---

## Daily operation

1. Record something real with OBS (the n8n canvas firing, a dashboard, a build)
2. Upload the raw file to `cdn.getnexalead.online/videos/raw/`
3. In the sheet: paste `raw_url`, write one sentence in `video_brief`, set
   `status = needs_render`
4. Walk away

Within the hour the pipeline writes the hook and script, renders, uploads,
and flips the row to `scheduled`. At `scheduled_datetime` the video autopilot
publishes it everywhere in the `platforms` column.

Your only recurring job is step 1.

---

## Cost

| Item | Monthly |
|---|---|
| Every platform API | $0 |
| GitHub Actions rendering | $0 (2,000 free min; a 45s video ≈ 3–5 min) |
| Cloudflare R2 | $0 (10GB + zero egress) |
| Kokoro TTS, WhisperX, FFmpeg, auto-editor | $0 |
| GPT-4o for hooks + captions | ~$1–2 |
| Hetzner CPX11 | ~€5 |
| **Total** | **~$7/mo for text + video across both brands** |

---

## Why it's built this way

**No generative AI video.** Nexalead sells "we deliver working systems, not
PDFs." Synthetic footage torches that positioning. The moat is that you can
show the actual machine running — nobody else in AI consulting can fake a real
screen recording of a working pipeline.

**Rendering runs off-box.** A CPX11 has 2 vCPU / 2GB and no swap by default.
FFmpeg encoding plus Whisper plus n8n plus Docker will trip the OOM killer.
GitHub's runners have 4 vCPU / 16GB and cost nothing.

**Captions are word-level, not line-level.** Karaoke highlighting is the single
biggest retention lever on Shorts and Reels, and it's free.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ass filter not found` | ffmpeg built without libass | `apt install libass9 ffmpeg` |
| Captions render but no font | Poppins missing | `fc-cache -f`, re-run installer |
| OOM during render | 2GB box, no swap | Installer adds 4GB swap; or render in Actions |
| Whisper takes forever | model too large | Use `--whisper-model base`, never `small`+ on 2 vCPU |
| TikTok posts invisible | app not audited | Expected. Posts stay `SELF_ONLY` until the audit passes (2–4 weeks) |
| Actions job skipped upload | R2 secrets missing | Falls back to artifact upload; add the 5 secrets |
| Video looks letterboxed | source is already 9:16 | Pass `--no-zoom`; the backdrop plate handles the rest |


---

## Fit mode cheat sheet

Tested against real 1920×1080 n8n canvas footage, not colour bars.

| Source | Flags |
|---|---|
| OBS screen capture | `--fit screencast --focus 0.6,0.5 --punch 2.1` |
| Phone video, near-vertical | `--fit fill` (default) |
| Already 9:16 | `--fit native --no-zoom` |

`--fit fill` on a 1920×1080 screencast shrinks 14px interface text to roughly
8px on the output — unreadable on a phone. That is what `screencast` mode
exists to solve. Set `--focus` on wherever the action happens: for an n8n
canvas where nodes light up on the right, `0.6,0.5` is correct.


---

## Cinematic layer (`cinema.py`)

Higgsfield's perceived quality comes from camera language, not from the
diffusion model. Camera language is deterministic motion design, so it is free
and it works on real footage — which matters, because a firm selling working
systems cannot post synthetic video of those systems.

### Camera moves

| Move | Use it for |
|---|---|
| `crash_zoom` | Violent 0.45s punch-in. Opening beat. |
| `dolly_in` | Slow continuous push. Never stops, reads as expensive. |
| `dolly_out` | Slow pull back. Reveal. |
| `whip_pan` | Fast lateral sweep with smear. Transition between shots. |
| `handheld` | Organic float. Kills the static-screenshot feeling instantly. |
| `orbit` | Slow arc around the centre. |
| `tilt_reveal` | Vertical reveal. Long dashboards. |
| `snap_zoom_out` | Tight, then snaps wide at 0.35s. Reveal beat. |

### Grades

| Grade | Look |
|---|---|
| `clean` | Punchy but colour-accurate. **Use for UI footage.** |
| `noir` | Deep blacks, cool shadows. Tech/SaaS. |
| `teal_orange` | Blockbuster contrast. |
| `warm_film` | Golden and soft. Armonía / hospitality. |
| `bleach` | Desaturated high contrast. Editorial. |

### Usage

```bash
vidkit --input raw.mp4 --out short.mp4 \
  --fit screencast --focus 0.6,0.5 --punch 2.1 \
  --move dolly_in --grade clean --bloom 0.25 \
  --hook "..." --script "..."
```

Preview any look without touching your footage:

```bash
python3 bin/cinema.py --list
python3 bin/cinema.py --demo look.mp4 --move crash_zoom --grade noir
```

### Sound design

`cinema.build_sfx()` synthesizes whooshes, sub-bass impacts, risers and ticks
from FFmpeg oscillators — no sample library, no licensing. `auto_cues()` picks
sensible hits for a given move: impact on the cut, whoosh on a crash zoom,
riser into the closing stat card.

### Why not generative AI video

Wan, LTX and Hunyuan need a 24GB+ GPU or per-clip cloud spend, and
photorealistic AI footage actively contradicts a "we deliver working systems,
not hype" position. Use generative only for abstract B-roll, never for
anything claiming to show your product. The moat is that your screen recording
is real.


---

## Style presets (`styles.py`)

Higgsfield's catalogue is mostly named *looks*, not camera moves. About two
thirds of them are colour, edge and texture transformations of existing
footage — deterministic image processing that costs nothing. 16 of those are
implemented here.

```bash
python3 bin/styles.py --list          # every preset, tagged UI-safe or photo
python3 bin/styles.py --impossible    # honest list of what needs diffusion
python3 bin/styles.py --demo look.mp4 --style toxic --source raw.mp4
```

| Preset | Look | Works on |
|---|---|---|
| `blueprint` | White linework on deep blue | **UI-safe** |
| `film_16mm` | 16mm stock, halation, grain | **UI-safe** |
| `vintage` | VHS chroma bleed, scanlines | **UI-safe** |
| `cold_vision` | Frozen clinical blue | **UI-safe** |
| `paper` | Printed, desaturated, textured | **UI-safe** |
| `toxic` | Thermal false-colour | photo only |
| `two_color` | Brand duotone | photo only |
| `ultraviolet` | Neon UV wash | photo only |
| `acid` | Drifting hue rotation | photo only |
| `ink_riot` | Black + one colour poster | photo only |
| `sketch` | Pencil edge detection | photo only |
| `comic` | Cel shading + linework | photo only |
| `halftone` | Newspaper dot pattern | photo only |
| `glitch` | RGB displacement, tearing | photo only |
| `fragments` | Stark black/white cutout | photo only |
| `overexposed` | Sun-bleached highlights | photo only |

### The UI-safe distinction matters

Tested against a real n8n canvas capture: on footage that is ~90% white, most
presets flatten the entire frame to a single colour and destroy legibility.
`toxic` becomes flat yellow, `two_color` flat green. On photographic footage
with real tonal range the same presets look correct.

**Rule: screen recordings get `blueprint`, `film_16mm`, `vintage`,
`cold_vision`, `paper` or nothing. Everything else is for B-roll.**

For Armonía that inverts — property and street footage is photographic, so the
whole library is available. `warm_film` grade plus `film_16mm` style is the
right default there.

### What genuinely needs a diffusion model

`styles.py --impossible` lists these honestly. Summary: anything that invents
new scenery (FAIRYTALE CASTLE, AGAMEMNON), composites subjects that were never
filmed together (DOLPHIN RIDE, SELFIE TWIN), rebuilds a subject in a new
material (ORIGAMI, MARBLE, BROKEN MIRROR), or does true painterly transfer
(MONET MUSE, HAND PAINT). No filter chain reproduces those. The closest free
approximations here are `paper` and `comic`.


---

## Generative B-roll (`generate.py`)

### What Higgsfield actually is

An aggregator. It resells Kling 3.0, Sora 2, Veo 3.1, WAN 2.6, Seedance,
Flux, Nano Banana and MiniMax under one credit system. It does not train its
own video models. Everything in its catalogue is reachable directly.

Its real economics, from 2026 reviews: subscription $15 Starter / $34–47 Plus
/ $84–99 Ultra. After the 3–5× iteration rate creators actually hit, a usable
Kling clip costs **$0.61–$1.18** and a usable Sora 2 or Veo 3.1 clip
**$3.36–$12**. Credits expire after 90 days. Generated files stop resolving
after 7 days.

### Direct cost, same models

```
$ python3 bin/generate.py --compare --seconds 5 --count 8

  option                               per clip   per month
  ---------------------------------------------------------
  wan (direct, fal)                      $0.250       $2.00
  ltx (direct, fal)                      $0.200       $1.60
  kling (direct, fal)                    $0.700       $5.60
  minimax (direct, fal)                  $0.500       $4.00
  veo (direct, fal)                      $2.500      $20.00
  local (direct, comfyui)                $0.000       $0.00

  Higgsfield kling (after retries)   $0.61-1.18  $4.88-9.44
  Higgsfield veo (after retries)     $3.36-12.00 $26.88-96.00
  Higgsfield subscription floor                   $15-99/mo
```

For the 4–8 abstract B-roll clips a month Nexalead would realistically use,
direct WAN costs **$1–2/month** against a $15–99 subscription floor.

### Three guarantees this module makes that a credit system cannot

1. **Hard spend cap.** `--cap` is enforced before the API call. It refuses and
   exits rather than overspending. Nothing can surprise-bill you.
2. **Permanent cache.** Prompts are hashed; an identical prompt never costs
   twice. Results download to `~/.vidkit/generated` immediately, so nothing
   expires after 7 days.
3. **A ledger.** `--ledger` shows exactly what you have spent this month.

```bash
python3 bin/generate.py --compare                    # cost table
python3 bin/generate.py --estimate --model wan --count 4
python3 bin/generate.py --prompt "abstract data through dark space" \
                        --model wan --seconds 5 --cap 3.00
python3 bin/generate.py --ledger
```

Without `FAL_KEY` set it runs as a dry run and prints what it *would* cost —
so you can always know the price before committing.

### The genuinely free path: ComfyUI

ComfyUI is the real open-source substitute — **126,967 stars, GPL-3.0**, with
first-party LTX templates and WAN support, and new models integrated within
days of release. Once you have the hardware, generation is free; the same work
on paid platforms runs $0.10–$2.00 per image. Marginal cost after setup: $0.

It needs a GPU. A rented Hetzner GEX44 is ~€184/mo, so it only beats per-clip
API pricing above roughly 700 clips a month. **At your volume, direct API is
cheaper than self-hosting.** Revisit if volume grows 100×.

There is also `ComfyUI-Higgsfield-Direct` on GitHub if you ever want
Higgsfield's own API without its credit UI — same models, your own key.

### The strategic point

None of this changes the core recommendation. Generative video is for
*abstract B-roll and openers only*. The moment a Nexalead video shows
synthetic footage of a working system, the entire "we deliver working systems,
not PDFs" position collapses. Real screen recordings are the moat; generated
clips are seasoning.

For Armonía it is looser — generated establishing shots of CDMX streets are
fine, since nobody is claiming they are the actual property.


---

## True zero-touch: the full loop

```
SUN 18:00  Auto-Scheduler reads what already went out + what performed,
           GPT-4o plans 7 days with no repeats, appends ~9 rows. Telegram ping.
              ↓
DAILY      Text Autopilot posts to 9 platforms. One AI call per batch.
              ↓
HOURLY     Render Pipeline turns any raw footage into a finished short.
              ↓
2x DAILY   Video Autopilot posts finished videos to 10 platforms.
              ↓
SAT 09:00  Performance Loop scores every hook from public engagement,
           writes the Performance tab, sends a digest.
              ↓
           …which the Sunday scheduler reads. The loop closes.
```

The system now writes its own briefs, avoids repeating itself, and leans
toward whatever actually performed. Your only recurring input is recording
footage when you feel like it.

### Activation order — do NOT do these at once

| # | Workflow | When to turn on |
|---|---|---|
| 1 | `nexalead-autopilot-v1` | **Now.** This is the one that generates leads. |
| 2 | `nexalead-performance-loop` | After 1 week of real posts exists to measure |
| 3 | `nexalead-auto-scheduler` | After the loop has one week of data to learn from |
| 4 | `nexalead-render-pipeline` | After CDN + R2 are live |
| 5 | `nexalead-video-autopilot-v1` | After the first render succeeds |

Turning the scheduler on before anything has posted means auto-generated
briefs feed an untested pipeline — two unknowns failing simultaneously.

---

## Preflight: `doctor.py`

Run this before flipping any switch, and any time something breaks.

```bash
python3 bin/doctor.py           # full check incl. network + selftest
python3 bin/doctor.py --quick   # skip network
python3 bin/doctor.py --fix     # print the exact remediation commands
```

Checks binaries, every FFmpeg filter the pipeline depends on, fonts, Python
libraries, module syntax, all 13 environment variables, disk, RAM, **swap**
(catches the CPX11 OOM trap before it kills a render), generative spend to
date, CDN and n8n reachability, OpenAI key validity, and runs the 21-assertion
render self-test.

Exits non-zero on any critical failure, so it can gate a deploy.


---

## Video without a camera (`datavid.py`)

The video pipeline had exactly one human dependency: *record something*. This
removes it. Five templates render a finished, branded, animated clip from
numbers alone, so the autopilot can publish video on days you never open OBS.

| Template | Use when the brief is | Example data |
|---|---|---|
| `stats` | 2–3 hard numbers | `47 posts\|12 platforms\|$2.14 cost` |
| `versus` | a cost or time comparison | `Agency $5000\|This system $30` |
| `canvas` | describing a workflow | `Read Calendar\|Write Copy\|Bluesky\|...` |
| `list` | "N things" | `Invoice matching\|Lead routing\|...` |
| `quote` | one contrarian claim | `Most AI consultants deliver a PDF.` |

```bash
python3 bin/datavid.py --list
python3 bin/datavid.py --demo-all --out /tmp/preview
python3 bin/datavid.py --template versus \
  --data "Agency \$5000|This system \$30" --title "monthly cost" --out v.mp4
```

`versus` computes the multiplier itself — feed it 5000 and 30 and it reveals
**167x CHEAPER**. Bars use a legibility floor so a $30 bar against $5,000
still reads instead of vanishing at 0.6% width.

### It runs itself

The render pipeline no longer requires `raw_url`. If a row has only a
`video_brief`, GPT-4o picks the template, writes the data, and dispatches
`datavid:stats:last week:47 posts|12 platforms|$2.14` as the source. Actions
generates the visual, then renders captions, camera move and grade over it.

Rows with footage still take the screencast path. Rows without take the data
path. Same queue, same output format, no human in either.

### Layout contract

`render.py` owns the accent rule, the URL tag and the caption band at y≈1290.
`datavid.py` therefore paints only between `SAFE_TOP = 380` and
`SAFE_BOTTOM = 1180` and draws no brand chrome. Break that and you get two
accent bars and two URLs stacked — which is exactly what happened before this
was enforced. The pipeline also blanks the render stats card on datavid rows,
because the generated visual already *is* the stats.

### What to actually publish

Best first video, no recording needed:

```
template: versus
data:     Agency $5000|This system $30
title:    monthly cost
hook:     This replaced a $5,000/mo agency.
```

That is your entire pitch in seven seconds, and every number in it is true.
