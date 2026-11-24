# ClipCutter: system design (website)

Goals, in order:
1. **Lowest possible cost.** Start at ₹0/month and keep it near zero per clip.
2. **Any length.** A 24-hour stream should be as easy as a 10-minute video.
3. **Easy on a phone.** Paste or share a link, see the best moments, tap to make a clip.
4. **Scale without a rewrite.** Same code from 1 user to 100k users. Only the hosting changes.

---

## 1. The key idea: analyse text, download only what becomes a clip

Normal tools download the whole video, transcribe all of it on a GPU, then cut. For a 24-hour stream that's
~40 GB of video and hours of GPU time, so long streams are slow and expensive everywhere.

ClipCutter flips it:

| Step | What it touches | 24 h stream | Cost |
|---|---|---|---|
| 1. Metadata | title, length, **"Most replayed" heatmap** (YouTube), caption track, chat replay | a few MB of text | ₹0 |
| 2. Signals per second | speech hype (captions), chat spikes, replay heatmap | 86,400 numbers, <1 s | ₹0 |
| 3. Candidates | top ~15 peaks → snapped to full sentences | <1 s | ₹0 |
| 4. Hooks (optional AI) | only the candidates' text (~10–15k tokens) | ~5 s | ₹0 (templates) / ~₹0.10 (Haiku) |
| 5. **Preview** | user sees moments in a YouTube player at that second, hook text on top | nothing rendered | ₹0 |
| 6. Clip on request | download **only that ~60 s** (stream copy, no re-encode, ~15 MB, ~20 s) → render 9:16 | 1 clip | ~₹0.03 CPU |

Measured: a 30 s section downloads in ~24 s, and its frames match the full video exactly (MP4 edit lists keep t=0 at the
requested second). Before this change, a section with re-encoding at the cuts took 6.5 minutes.

**Fallback when there are no captions:** download audio only (~50 MB/hour), find loud and chat peaks, and run speech-to-text only on
those windows (CPU, faster-whisper).

**Limits to know:** YouTube only archives the first 12 hours of a live stream (a platform limit). Twitch keeps VODs up to 48 h.
Both work.

---

## 1b. Live mode (clip while the stream is live)

| Step | How | Cost |
|---|---|---|
| Record | yt-dlp resolves the HLS URLs; ffmpeg records 720p in 5-min `.ts` segments, stream copy | ~0 CPU, 1.5–3 GB/h bandwidth |
| Chat | Twitch anonymous IRC / YouTube live chat via yt-dlp, wall-clock timestamps | ₹0 |
| Per segment | loudness + smart chat votes (per-user cap, paid/gift weight, burst bonus), resonance, quality gate | <1 s |
| Clip | only strong moments: transcribe that window, hook, render from the local segment(s) | ~30–60 s per clip |

Clips land about one segment length behind the stream. The worker runs up to 2 live sessions (`MAX_LIVE`) in
threads. A heartbeat requeues sessions whose worker died. Recorders are stopped when the worker exits. Free plan:
30 min per session, paid: 12 h. Every clip uses one credit, and the session stops when credits run out.

## 2. Architecture

```
          📱 phone / 💻 browser (PWA, share-sheet target)
                      │  HTTPS
              ┌───────▼────────┐
              │  Caddy (TLS)   │  free certificates
              └───────┬────────┘
              ┌───────▼────────┐        ┌──────────────────────────┐
              │  Web/API       │◄──────►│  Database                │
              │  FastAPI       │        │  SQLite (start)          │
              │  - auth        │        │  → Postgres (scale)      │
              │  - plans/quota │        │  jobs = rows, no Redis   │
              │  - preview     │        └──────────▲───────────────┘
              └───────┬────────┘                   │ claim job (atomic UPDATE)
                      │ files                      │
              ┌───────▼────────┐        ┌──────────┴───────────────┐
              │  Storage       │◄──────►│  Workers (1..N)          │
              │  local disk    │        │  - analyse video (text)  │
              │  → R2 (scale)  │        │  - render clip (ffmpeg)  │
              └────────────────┘        │  CPU only, no GPU        │
                                        └──────────────────────────┘
```

- **Web/API and workers are separate processes.** A slow render never blocks the website, and more workers can be added on more
  machines.
- **Queue = database rows.** Jobs are claimed with an atomic `UPDATE … WHERE status='queued'`. No Redis or RabbitMQ to run or pay for.
  On Postgres this becomes `SELECT … FOR UPDATE SKIP LOCKED`, still with no extra service.
- **Shared analysis cache by video ID.** When 100 users clip the same GTA 6 stream, it's analysed once. Downloaded sections
  are cached too, so the same moment is downloaded once.
- **Stateless web tier.** Sessions live in the database, so web servers can be added behind a load balancer.

## 3. Data model

| table | key fields |
|---|---|
| `users` | email, password hash (scrypt), plan, plan_until |
| `sessions` | random token (HttpOnly cookie), user, expiry |
| `videos` | key (platform:id), url, title, duration, status, progress, analysis path. **Shared by all users** |
| `user_videos` | which user asked for which video (their history) |
| `clips` | user, video, moment, status, progress, file path, created. **Counts against the monthly quota** |

## 4. Plans and quota

| plan | price | clips / month | max video length | extras |
|---|---|---|---|---|
| Free | ₹0 | 10 | 3 h | small watermark |
| Starter | ₹199 (₹1,990/yr) | 50 | 24 h | no watermark |
| Creator | ₹499 (₹4,990/yr) | 150 | 24 h | priority queue |
| Pro | ₹1,499 (₹14,990/yr) | 500 | 24 h | better AI model |

- Analysis is free and unlimited (fair-use rate limit). **Only rendered clips count**, which is what costs money.
- A clip counts when it's queued. Failed clips are refunded automatically.

## 5. Cost model

| item | per clip |
|---|---|
| AI (Haiku, optional) | ~₹0.04 |
| CPU render (₹1,250/mo 8-core ≈ 1,500 clips/day) | ~₹0.03 |
| storage (deleted after 7 days) / egress (R2: free) | ~₹0 |
| **total without proxy** | **~₹0.10** |
| residential proxy, *only if* YouTube blocks the server IP | +₹5–8 |

Fixed: ₹0 (Oracle Cloud Always Free: 4 ARM cores, 24 GB RAM) to ~₹1,500/month (Hetzner).

**Biggest risk: YouTube blocking datacenter IPs.** In order of preference:
1. a JS runtime (Deno/Node) for yt-dlp
2. section-only downloads (few requests)
3. the shared cache
4. a "laptop agent" mode, where the user's own machine downloads
5. a proxy only for paid plans

## 6. Scaling path (no rewrite)

| users | change |
|---|---|
| 0–500 | 1 VM: Caddy + web + 1 worker + SQLite + local disk |
| 500–5k | 2–3 worker VMs, switch `DATABASE_URL` to Postgres (Supabase/Neon free), storage to R2 |
| 5k+ | autoscale workers on queue length, CDN for clip downloads, per-region workers |

## 7. Reliability and safety

- Jobs survive restarts (state in DB). Stuck jobs are re-queued after a timeout. Failed clips are refunded.
- Cleanup: clips after 7 days, sections after 2 days, analysis after 30 days.
- Security: scrypt password hashes, HttpOnly + SameSite session cookies, per-IP login rate limit, URL allow-list
  (YouTube, Twitch, Kick only, which also blocks SSRF), files only served to their owner.
- Abuse: per-user concurrent job limits, max video length per plan.
- Legal: users confirm they have the rights to clip (own content or a clipper program). DMCA contact on the site.

## 8. What's next

- Payments: Razorpay subscriptions (monthly/yearly) → webhook sets `plan` and `plan_until`.
- Laptop agent: the phone sends a link, the user's computer does the download and render.
- Auto-posting (YouTube Shorts / Instagram / TikTok official APIs).
