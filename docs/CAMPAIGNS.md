# Clipping campaigns: how to stay approved

ClipCutter has presets for the campaigns we've joined on Content Rewards (Whop). A preset puts everything the
brief requires into the clip and the post caption, so you don't have to edit anything by hand.

```bash
# only the gameplay part of the stream (skip the "just chatting" start), with Bobby's rules applied
uv run clipcutter run "https://www.twitch.tv/videos/<id>" --clips 4 --from 100m --campaign bobby
```

| flag | what it does |
|---|---|
| `--campaign bobby\|kreekcraft\|luckylatvian` | on-screen label, a CTA end card (last 3 s), the required logo overlay, censored captions, and the exact post caption and hashtags (`post_caption` in `clip_XX.json`) |
| `--from 100m` / `--to 3:30:00` | only pick moments inside this part of the stream |

Presets live in `src/clipcutter/campaigns.py`. Logo overlays go in `assets/campaigns/`.

## Before you post: checklist (every campaign)

1. **Watch the whole clip.** It must be real GTA 6 gameplay or a stream moment of *that* streamer. No just-chatting, no
   other games, no South Park or YouTube watch-alongs.
2. **The hook must be true.** It should describe what actually happens. Briefs reject misleading titles and fabricated context.
3. **Check the picture quality.** No heavy blocking. Some stream moments have a low bitrate, so skip those.
4. **Use the caption from `post_caption` as-is.** It includes the required CTA and hashtags.
5. **Keep likes visible** on Instagram and YouTube. Hidden likes mean rejection.
6. **Keep the post up for 30 days** or more.
7. **Submit the link on Content Rewards within 30 minutes** of posting.
8. Don't post the same or a nearly identical clip more than 5 times, and never buy or bot views.
9. Account: a gaming or streamer clip page. A new account needs the campaign's warm-up first: a few days of normal
   scrolling, likes and follows in the niche, before the first post.

## Per campaign

| | Bobby Van Riper | KreekCraft | Lucky Latvian |
|---|---|---|---|
| Rate | $1.50 / 1K views (min $2.25, max $150) | $1 / 1K (min $5, max $300) | $2 / 1K (min $10, max $100) |
| Source | Bobby's GTA VI streams only | KreekCraft's official GTA 6 streams / replays only | any GTA 6 gameplay or stream moment |
| On screen | twitch.tv/bobby_vanriper + "Follow Bobby Vanriper on Twitch" (the preset adds both) | **official logo overlay for the whole clip** (preset adds it) | the CTA from the campaign's Drive folder |
| Caption | CTA + twitch link + #bobbyvanriper ... | "Watch KreekCraft on YouTube and Twitch" + #GTA6 #KreekCraft #GrandTheftAutoVI, **no links** | CTA as provided, no claims of your own |
| Audience | ≥40% US/UK/CA/AU, English | ≥40% US/UK/CA/AU | EU first |
| Engagement | ≥1% | ≥0.8% | n/a |
| Payout step | Clipping Nation Discord; at 1,500 views open a "Submit Demographics" ticket with a screen recording of country analytics | ClipLaunch Discord (discord.gg/cliplaunch) | Telegram t.me/klipzyIO |

**Tier-1 audience, honestly:** post in US prime time (9 PM–2 AM IST), keep captions in English, and use streamer and
GTA hashtags. Do not use a VPN, bought views, or "story boosting". Campaigns ban these, and it costs the whole account.

## Non-gaming: Stream House LA (`--campaign streamhousela`)
This is a CWETV reality show, so post it on a **separate entertainment account**, never on the GTA pages. The preset adds
a CWETV CTA end card and the 4 required hashtags, and it adds no watermark. By hand, you still need to:
1. write a fresh on-screen title for each clip (cast name first)
2. tag the cast member
3. post a story with the cwenetwork buy link for every clip

Account setup: `output/brand/streamla/SETUP.md`.
