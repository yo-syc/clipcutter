"""Clipping-campaign presets: what each brief requires on screen and in the post caption.

`clipcutter run <url> --campaign bobby` applies one. Every rule here comes from the campaign's brief,
so a clip is compliant without hand edits: CTA on screen, required logo overlay, censored captions,
exact caption text + hashtags. Add new campaigns to PRESETS.
"""
from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "campaigns"

PRESETS: dict[str, dict] = {
    "bobby": {
        "name": "Bobby Van Riper GTA VI (Clipping Nation)",
        "label": "twitch.tv/bobby_vanriper",          # on screen the whole clip (brief: on screen or in caption)
        "cta": "Follow Bobby Vanriper on Twitch 🔴",  # end card: name + where to watch live
        "logo": None,                                  # overlay optional for this brief
        "caption_tail": "Follow Bobby Vanriper on Twitch: twitch.tv/bobby_vanriper",
        "hashtags": ["#bobbyvanriper", "#gta6", "#gtavi", "#twitch", "#streamer", "#twitchclips", "#gaming",
                     "#funnymoments"],
        "rules": [
            "Source: only Bobby's GTA VI streams/videos (gameplay, not just-chatting)",
            "Hook in the first 2 s, one clear moment, CTA with Bobby's name + Twitch",
            "#bobbyvanriper + twitch.tv/bobby_vanriper on screen or in caption, English captions",
            "Likes visible, post stays up 30 days, >=1% engagement, gaming/streamer-niche account",
            "Submit link within 30 min; at 1,500 views send country analytics (Discord ticket)",
            "No 1:1 copies, max 5 near-identical posts, no AI thumbnails, no negative portrayal",
        ],
    },
    "kreekcraft": {
        "name": "KreekCraft GTA 6 (ClipLaunch)",
        "label": None,
        "cta": "Watch KreekCraft on YouTube and Twitch 🔴",
        "logo": "kreekcraft_overlay.png",              # REQUIRED for the whole clip, or it's rejected
        "facecam": (0.0, 0.05, 0.218, 0.38),           # his webcam box (x, y, w, h as fractions), top-left on every stream
        "caption_tail": "Watch KreekCraft on YouTube and Twitch! 🔴",   # no links allowed in caption
        "hashtags": ["#GTA6", "#KreekCraft", "#GrandTheftAutoVI"],
        "rules": [
            "Source: only KreekCraft's official GTA 6 livestreams / replays",
            "Official logo overlay visible from start to finish",
            "Caption: 'Watch KreekCraft on YouTube and Twitch' + #GTA6 #KreekCraft #GrandTheftAutoVI, NO links",
            "Hook in 1-2 s, accurate context, no misleading titles",
            "Likes visible, >=0.8% engagement, stays up 30 days, max 5 near-identical posts",
        ],
    },
    "luckylatvian": {
        "name": "Lucky Latvian x GTA6 (KLIPZY)",
        "label": None,
        "cta": None,                                   # set from the CTA in the campaign's Drive folder
        "logo": None,
        "caption_tail": "",
        "hashtags": ["#gta6", "#gtavi", "#gaming"],
        "rules": [
            "GTA 6 only: gameplay, stream moments, NPC chaos, fails, story moments",
            "Hook in the first second, 9:16",
            "Use Lucky Latvian's CTA exactly as provided; no own claims about the brand",
            "No reuploads of others' edits, no bought views",
        ],
    },
    "dylanpage": {
        "name": "Dylan Page GTA VI Marathon (NewsDaddy)",
        "cam_frac": 0.5,                               # Dylan must be the main focus: half the screen is his cam
        "label": None,                                 # brief: NO added watermarks or third-party branding
        "cta": None,
        "logo": None,
        "caption_tail": "",
        "hashtags": ["#DylanPage", "#gta6", "#gtavi"],
        "rules": [
            "Footage: Dylan Page's GTA 6 marathon (from Nov 19, 2026), live, VOD or clips",
            "Dylan must be the main focus for the whole clip, 9:16, English captions",
            "#DylanPage in the caption; no added watermarks/branding; unique thumbnail per clip",
            "No misleading edits or out-of-context clips",
        ],
    },
    "dasgasd3m": {
        "name": "Dasgasd3m x RUCKUS GTA 6",
        "label": None,
        "cta": None,
        "logo": None,
        "caption_tail": "",
        "hashtags": ["#dasgasd3m", "#gta6", "#gtavi", "#kick"],
        "rules": [
            "Footage: Dom's GTA 6 streams on kick.com/dasgasd3m from Nov 18, 2026 (live or VOD)",
            "GTA 6-specific TikTok/YouTube Shorts account; keep his face or voice in the edit",
            "Read the full brief + creator requirement in Content Rewards before posting; deadline Dec 19, 2026",
        ],
    },
    "boeshi": {
        "name": "Boeshi GTA 6 (ClipLaunch)",
        "label": "twitch.tv/darealboeshi",
        "cta": "Watch Boeshi live on Twitch 🔴",
        "logo": None,
        "caption_tail": "Watch Boeshi live on Twitch: twitch.tv/darealboeshi",
        "hashtags": ["#boeshi", "#gta6", "#gtavi", "#twitch", "#streamer"],
        "rules": [
            "Footage: Boeshi's GTA 6 Twitch streams; reactions, chases, chaos",
            "Drive viewers to twitch.tv/darealboeshi; full rules in the campaign's Notion brief",
        ],
    },
    "diegoloveless": {
        "name": "DiegoLoveless GTA 6 (ClipLaunch)",
        "label": "twitch.tv/diegoloveless",
        "cta": "Follow DiegoLoveless on Twitch 🔴",
        "logo": None,
        "caption_tail": "Follow DiegoLoveless on Twitch: twitch.tv/diegoloveless",
        "hashtags": ["#diegoloveless", "#gta6", "#gtavi", "#twitch", "#streamer"],
        "rules": [
            "Every clip MUST show Diego playing GTA 6, with a clear CTA to his Twitch",
            "Full rules in the campaign's Notion brief",
        ],
    },
    "asianjeff": {
        "name": "AsianJeff GTA 6 (Reach)",
        "cam_frac": 0.5,                               # AsianJeff must be the main focus
        "label": None,                                 # brief: logos of any kind are not allowed
        "cta": None,
        "logo": None,
        "caption_tail": "",
        "hashtags": ["#AsianJeff", "#gta6", "#gtavi"],
        "rules": [
            "Footage: AsianJeff's GTA 6 playthrough from Nov 19, 2026 only (twitch.tv/asianjeff)",
            "AsianJeff is the main focus; funny moments, quotes, reactions; no rage-bait/drama framing",
            "#AsianJeff in caption, no logos, >=50% US/CA/AU/UK/NZ audience",
            "Payout only after 10,000 views (MVR) + approval; submit within 30 min",
        ],
    },
    "streamhousela": {
        "name": "Stream House LA (Motion Clipping, CWETV)",
        "label": None,                                 # brief: no personal watermarks
        "cta": "Watch Stream LA on CWETV 📺",          # CWETV CTA on screen in every clip
        "logo": None,
        "caption_tail": "Full episodes on CWETV, link in bio 📺 @streamhousela",
        "hashtags": ["#streamhouselacwe", "#streamhousela", "#cwetv", "#chickenwrapentertainment"],
        "rules": [
            "NOT gaming: post only on the dedicated entertainment account, never on the GTA pages",
            "Source: Stream LA episodes (CWETV); arguments, reactions, quotable lines, cast interactions",
            "On-screen title every clip, cast name first, plain font; never reuse a title or caption",
            "Tag the right cast member (handles in the strategy doc) + the 4 hashtags + CWETV CTA in caption",
            "Every clip: an Instagram story with https://www.cwenetwork.com/buy?campaign=motionclipping",
            "Target US/UK/CA; no bots; paid to Whop 4 days after approval",
        ],
    },
}


def apply(cfg: dict, name: str) -> dict:
    """Turn a preset into render settings on cfg. Returns the preset."""
    if name not in PRESETS:
        raise SystemExit(f"unknown campaign '{name}'. Known: {', '.join(PRESETS)}")
    p = PRESETS[name]
    cfg["campaign"] = name
    cfg["captions"]["censor"] = True     # brand-safe captions for every campaign
    if p["label"]:
        cfg["watermark"] = p["label"]
    cfg["cta"] = p["cta"]
    if p.get("cam_frac"):
        cfg["cam_frac"] = p["cam_frac"]
        cfg["layout"] = "split"
    if p.get("facecam"):   # known webcam position beats per-clip detection (hair/hats/lighting fool it)
        cfg["facecam"] = p["facecam"]
        cfg["layout"] = "split"
    if p["logo"]:
        logo = ASSETS / p["logo"]
        if not logo.exists():
            raise SystemExit(f"campaign '{name}' needs its logo overlay at {logo} (download it from the brief)")
        cfg["logo"] = str(logo)
    return p


def post_caption(name: str, hook_line: str) -> str:
    p = PRESETS[name]
    return " ".join(x for x in (hook_line, p["caption_tail"], " ".join(p["hashtags"])) if x).strip()
