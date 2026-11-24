# ClipCutter — Plan

Goal: give it a stream (live or VOD) and get back ready-to-post vertical clips, each with a hook and a payoff, posted automatically. It should run on your own Mac with no paid third-party service required, so the cost per clip is close to zero. Later it can be packaged and sold.

---

## 1. Why build our own

| | Opus Clip / Eklipse / StreamLadder etc. | ClipCutter (ours) |
|---|---|---|
| Cost | ~$10–30/month, credit limits | Free to run (your Mac does the work) |
| Gaming/stream aware | Generic "talking head" logic | Uses **chat spikes + audio + game moments** |
| Live streams | Mostly VOD only | Clips **while the stream is still live** |
| Hook control | Template | Our own hook-first edit |
| Sellable | No | Yes: one-time license, users run it locally |

The edge: generic tools cut on speech alone. Gaming streams need **chat reactions + loudness + what's happening on screen**. That is what makes GTA clips go viral.

### Competitor check (Nov 2026)

| | Opus Clip | Eklipse | StreamLadder | Klap / Submagic | **ClipCutter** |
|---|---|---|---|---|---|
| Price | from ~$15/mo, credit limits | $24.99/mo | AI clipping on $27/mo plan | ~$20–30/mo | **free, unlimited (runs on your Mac)** |
| Moment detection | speech + virality score | game events (kills) | AI on top plan | speech | **chat spikes + loudness + scene cuts + speech** ✅ |
| Chat signal | ❌ | partial | ❌ | ❌ | ✅ |
| Track other creators automatically | ❌ | ❌ | ❌ | ❌ | ✅ **creator tracker + discovery** |
| Any platform link | YouTube etc. | Twitch/YT/Kick | Twitch/YT/Kick | YouTube | ✅ ~1000 sites via yt-dlp |
| Long VODs cheaply | uploads full video | full VOD | full VOD | full video | ✅ **audio first, video only for clips** |
| Hook-first edit | ❌ (cuts in order) | ❌ | ❌ | ❌ | ✅ cold-open hook → rewind → payoff |
| Virality score | ✅ | ❌ | ❌ | ❌ | ✅ 0–99 |
| Facecam split layout | reframing | ✅ | ✅ (main feature) | reframing | ✅ auto-detected |
| Auto-post / scheduler | ✅ (users report silent failures) | ✅ | ✅ | ✅ | ⏳ next |
| Caption languages | many | some | some | 100+ (Submagic) | Whisper: 99 languages (Hindi too) |
| Clips while still live | ❌ | ✅ | ❌ | ❌ | ⏳ next |

**Still to build to beat all of them:** reliable auto-posting with retries, GTA 6 game-event detection (WASTED / BUSTED / wanted-star screens), live-mode clipping, Hinglish/Hindi caption styling, a feedback loop that learns from each clip's views, and a mobile-friendly review page.

---

## 2. How it works (fully automatic)

```
 Stream URL (Twitch / YouTube / Kick) or local file
        │
 [1] INGEST      yt-dlp / streamlink → video + chat log
        │         (live mode: record in 10-min chunks, process each chunk)
 [2] UNDERSTAND  whisper.cpp (runs on the M5 GPU) → transcript with word timings
        │         ffmpeg → loudness curve, scene cuts
        │         chat → messages/sec, emotes ("LUL", "KEKW", "W", "CLIP IT", "😂")
 [3] SCORE       combine signals → "virality score" per second → top N moments
        │
 [4] CUT         snap start/end to sentence boundaries (15–60 s clips)
        │
 [5] EDIT        • HOOK: first 1–3 s = the peak moment (cold open) + bold hook text
        │         • MAIN: rewind to the setup → build-up → payoff
        │         • 9:16 layout: facecam on top, gameplay below (or smart crop)
        │         • word-by-word animated captions, emoji, zoom-punch on peak
        │         • optional end loop so it replays seamlessly
 [6] WRITE       title, description, hashtags (#GTA6 #GTAVI …) per platform
        │
 [7] EXPORT      ffmpeg + Apple hardware encoder (fast, free)
        │
 [8] POST        queue + scheduler → YouTube Shorts / TikTok / Instagram Reels
```

### Highlight score (step 3)
```
score = 0.40 * chat_spike        (messages/sec vs. the stream's own average)
      + 0.25 * audio_spike       (sudden loudness: screaming, explosions)
      + 0.20 * transcript_hype   (LLM rates the sentence: funny / shocking / clutch)
      + 0.15 * visual_action     (scene-change rate, motion)
```
Weights get tuned later from real view counts (the clips that performed teach the scorer).

### Hook + Main structure (step 5)
```
0.0–2.5s   HOOK   peak frame/line + big text: "HE DID NOT SEE THAT COMING 💀"
2.5–Xs     MAIN   setup → tension → payoff (the full moment, in order)
last 1s    LOOP   cut back to near the hook so the clip replays
```
Hook text is chosen from 3 LLM-generated options, picking the one with the strongest curiosity gap.

### Gen Z style (the default vibe)
The whole clip should feel like Gen Z TikTok, not a corporate edit.

**Hook text: short, lowercase, chaotic**
- "bro really thought he was him 💀"
- "nah this cop is NOT real 😭"
- "the way he just— 🫠"
- "wait for it…"
- "GTA 6 cops are built different fr"
- "he's cooked 🔥🔥"

**Captions**
- 1–3 words at a time, pop-in animation, the active word highlighted (yellow or green)
- emoji dropped on reactions (💀 😭 🔥 🫡 😳)
- all lowercase, slang kept as said ("ong", "fr", "no cap", "lowkey", "aura", "cooked", "rizz")

**Editing**
- zoom-punch + shake on the peak, a quick freeze frame, then "bro 💀"
- meme sound effects on the hook (vine boom, bruh, record scratch), all royalty-free
- no slow intros, ever: something happens in the first 0.5 s
- the loop ending makes people rewatch

**Titles and captions on the post**
- "gta 6 got me crashing out 😭 #gta6 #gtavi #fyp"
- question bait for comments: "who's fault was this 💀"

**Configurable:** `style: genz | hype | clean`. The LLM gets a Gen Z prompt and a list of banned "cringe" words (no "epic", "awesome", or "check this out").

---

## 3. Tech stack (cheap / free first)

| Job | Tool | Cost |
|---|---|---|
| Download VOD + chat | `yt-dlp`, `chat-downloader` | Free, open source |
| Record live | `streamlink` | Free |
| Transcribe | `whisper.cpp` (Metal GPU on the M5) | Free, local |
| Hook text / titles / hype score | **Ollama** (local Llama/Qwen) by default; optional Claude Haiku API for better quality (fractions of a cent per clip) | Free, or ~$0.001/clip |
| Face detection for crop | MediaPipe / OpenCV | Free |
| Edit + captions + render | `ffmpeg` (already installed) + ASS subtitles | Free |
| Pipeline | Python 3.12 | Free |
| UI (later) | Local web dashboard (FastAPI + simple React), then a Tauri desktop app to sell | Free |
| Database / queue | SQLite | Free |

Everything is open source and runs locally, so there is no vendor lock-in. The only optional paid piece is a better LLM for hooks.

---

## 4. Auto-posting: what's possible

| Platform | Official API | Reality |
|---|---|---|
| **YouTube Shorts** | YouTube Data API (`videos.insert`) | ✅ Works. Free quota of about 6 uploads/day per project (an increase can be requested). Vertical + under 3 min = Short. |
| **TikTok** | Content Posting API | ⚠️ Works, but until the app passes TikTok's audit, posts go out **private only**. Apply for the audit early. Fallback: upload as a draft to the TikTok inbox and publish with one tap. |
| **Instagram Reels** | Instagram Graph API | ✅ Needs an Instagram **Business/Creator** account linked to a Facebook Page. The video must be at a public URL while it uploads (a temporary link is enough). |
| **X / Twitter** | X API | 💰 Paid tier needed. Skip for now. |
| Facebook Reels | Graph API | ✅ Same setup as Instagram. |

We'll use **official APIs only**. Browser-bot posting gets accounts banned. That matters a lot if we sell this.

Scheduler: spread posts out (for example every 2–3 h at peak times), never post the same clip twice, and keep a "review queue" mode for anyone who wants to approve each clip before it goes out.

---

## 5. Rules to respect (important for selling)

- **Only clip streams you own or have permission for.** Many big streamers run official "clipper programs" that pay clippers, and this tool fits that model. Re-uploading other people's streams without permission gets you copyright strikes and demonetized.
- Rockstar generally allows gameplay videos, but avoid leaks or spoilers before official release.
- The product should show a "content you have rights to" checkbox and a per-channel permission list.

---

## 6. Build phases

**Phase 1 — MVP (CLI, ~1 week)**
`clipcutter run <vod-url>` → 5 vertical clips with captions + hook text, saved to `output/`.
- ingest (yt-dlp + chat) → whisper.cpp → scoring → cut → 9:16 render with captions

**Phase 2 — Smart editing**
- facecam detection + split layout, zoom-punch, sound-effect on hook, loop ending
- LLM hook/title generation, emoji captions, GTA-specific keyword boosts (cops, wanted level, heist, crash)

**Phase 3 — Live mode**
- record live in chunks, output clips **during** the stream (first to post wins in the GTA 6 rush)

**Phase 4 — Auto-post**
- YouTube → Instagram → TikTok connectors, scheduler, posting history, simple analytics pull (views/likes) fed back into the scorer

**Phase 5 — Product to sell**
- local web dashboard → Tauri desktop app (Mac + Windows)
- license keys via Lemon Squeezy / Gumroad
- pricing idea: **free tier** (3 clips/stream, watermark) · **one-time $29–49** or **$5/month** (much cheaper than the $15–30/month competitors, and still profitable because the user's computer does the work and there are no server costs for us)

---

## 7. Folder layout (planned)

```
CLIPCutter/
  clipcutter/
    ingest/      # yt-dlp, streamlink, chat download
    analyze/     # whisper, audio, chat, scene signals
    score/       # highlight scoring + boundary snapping
    edit/        # hook, layout, captions, ffmpeg render
    write/       # titles / hashtags (LLM)
    publish/     # youtube, instagram, tiktok + scheduler
    cli.py
  config.yaml    # weights, clip count, caption style, posting schedule
  output/
```

---

## 8. Needed from you before posting works
1. A Google Cloud project with YouTube Data API enabled (OAuth client)
2. An Instagram Business/Creator account linked to a Facebook Page and a Meta developer app
3. A TikTok developer app (and the audit application submitted early)
4. A test stream/VOD you own to tune on
