"""Policy pages payment gateways (Razorpay etc.) require: terms, privacy, refunds, shipping/delivery, contact.

Business details come from environment variables (set them in .env on the server), so no personal
data lives in the code:
    CLIPCUTTER_BUSINESS_NAME, CLIPCUTTER_EMAIL, CLIPCUTTER_PHONE, CLIPCUTTER_ADDRESS
"""
from __future__ import annotations

import html
import os

UPDATED = "19 November 2026"


def _biz() -> dict:
    return {
        "name": os.environ.get("CLIPCUTTER_BUSINESS_NAME", "ClipCutter"),
        "email": os.environ.get("CLIPCUTTER_EMAIL", "support@example.com"),
        "phone": os.environ.get("CLIPCUTTER_PHONE", ""),
        "address": os.environ.get("CLIPCUTTER_ADDRESS", ""),
    }


def _pages(b: dict) -> dict[str, tuple[str, str]]:
    n, e = html.escape(b["name"]), html.escape(b["email"])
    return {
        "terms": ("Terms of Service", f"""
<p>These terms apply to the ClipCutter website and app (the "Service") operated by <b>{n}</b>. By creating an account you agree to them.</p>
<h2>1. The Service</h2><p>ClipCutter finds highlights in videos you link to and turns them into short vertical clips. Finding moments is free.
Making a clip uses one credit from your monthly plan.</p>
<h2>2. Your account</h2><p>You are responsible for your account and password. One person per account. We may suspend accounts that abuse the
Service, try to get around limits, or break these terms.</p>
<h2>3. Content and rights</h2><p>You may only clip and publish content you own or have permission to use (for example, your own streams or a
creator's official clipper program). You are fully responsible for what you clip and post. We act on valid copyright notices sent to {e}.</p>
<h2>4. Plans and payments</h2><p>Paid plans are billed monthly or yearly in advance, in Indian Rupees, through our payment partner. Plans renew
automatically until you cancel. Unused credits don't roll over to the next month. Prices may change with 30 days' notice for the next billing period.</p>
<h2>5. Availability</h2><p>We work to keep the Service running but don't guarantee it will always be available or error-free. Clips are stored
for 7 days. Please download what you want to keep.</p>
<h2>6. Liability</h2><p>To the extent the law allows, our total liability for any claim is limited to the amount you paid us in the 3 months
before the claim.</p>
<h2>7. Changes and law</h2><p>We may update these terms. We will post the new date on this page. These terms are governed by the laws of India.</p>
<p>Questions: {e}</p>"""),
        "privacy": ("Privacy Policy", f"""
<p>This policy explains what <b>{n}</b> collects when you use ClipCutter and why.</p>
<h2>What we collect</h2><ul>
<li><b>Account:</b> your email address and a securely hashed password (we never see your password).</li>
<li><b>Usage:</b> the video links you add, the clips you make, and your plan and usage counts.</li>
<li><b>Payments:</b> handled by our payment partner (Razorpay). We don't store card or bank details.</li>
<li><b>Technical:</b> a login cookie to keep you signed in, and standard server logs (IP address, time) for security.</li></ul>
<h2>How we use it</h2><p>To run the Service, enforce plan limits, prevent abuse, and contact you about your account. We don't sell your data.</p>
<h2>Retention</h2><p>Clips are deleted after 7 days. Video analysis is deleted after 30 days. Your account data is kept until you ask us to delete it.</p>
<h2>Third parties</h2><p>Video previews are embedded from YouTube (youtube-nocookie.com). Payments are processed by Razorpay under their own privacy policy.</p>
<h2>Your rights</h2><p>You can ask for a copy of your data or ask us to delete your account by emailing {e}.</p>"""),
        "refunds": ("Refund & Cancellation Policy", f"""
<h2>Cancellation</h2><p>You can cancel a paid plan anytime. You keep your plan until the end of the period you already paid for. After that it
won't renew and your account moves to the Free plan.</p>
<h2>Refunds</h2><ul>
<li>Clips that fail are refunded automatically as credits.</li>
<li>If you were charged twice, or charged after cancelling, email {e} within 7 days and we'll refund the extra charge in full.</li>
<li>If the Service didn't work for you and you used fewer than 3 clips of a new paid plan, you can ask for a full refund within 7 days of payment.</li>
<li>Otherwise, payments for a period that has started are not refunded.</li></ul>
<p>Approved refunds go back to the original payment method within 5–7 working days.</p>"""),
        "shipping": ("Shipping & Delivery Policy", f"""
<p>ClipCutter is a fully online service. Nothing is shipped physically.</p>
<p>Your plan is active as soon as the payment succeeds, and the clips you make are delivered in your account (Library → Download), usually
within a few minutes. If a paid plan isn't active within 30 minutes of payment, email {e} and we'll fix it the same day.</p>"""),
        "contact": ("Contact Us", f"""
<p>We're happy to help with your account, plans, payments or anything else.</p>
<ul><li><b>Email:</b> <a href="mailto:{e}">{e}</a></li>
{f'<li><b>Phone:</b> {html.escape(b["phone"])}</li>' if b["phone"] else ''}
{f'<li><b>Address:</b> {html.escape(b["address"])}</li>' if b["address"] else ''}
<li><b>Business:</b> {n}</li></ul>
<p>We usually reply within 24 hours on working days.</p>"""),
    }


def render(page: str) -> str | None:
    pages = _pages(_biz())
    if page not in pages:
        return None
    title, body = pages[page]
    links = " · ".join(f'<a href="/legal/{k}">{v[0].split(" ")[0] if k != "refunds" else "Refunds"}</a>' for k, v in pages.items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · ClipCutter</title><link rel="icon" href="/static/icon.svg">
<style>:root{{--bg:#08080c;--txt:#e9e9ef;--mut:#9494a6;--acc:#c8ff2e;--line:#22222e}}
body{{margin:0;background:var(--bg);color:var(--txt);font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}}
main{{max-width:760px;margin:auto;padding:28px 20px 60px}} a{{color:var(--acc)}} h1{{font-size:32px;line-height:1.15;letter-spacing:-.8px;margin:24px 0 6px}}
h2{{font-size:19px;margin:26px 0 6px}} p,li{{color:#c9c9d4}} .up{{color:var(--mut);font-size:14px}}
nav{{border-bottom:1px solid var(--line);padding-bottom:14px;font-size:14px}} .logo{{font-weight:900;color:var(--txt);text-decoration:none;margin-right:14px}} .logo b{{color:var(--acc)}}
footer{{margin-top:40px;border-top:1px solid var(--line);padding-top:14px;font-size:14px;color:var(--mut)}}</style></head>
<body><main><nav><a class="logo" href="/">clip<b>cutter</b></a> {links}</nav>
<h1>{title}</h1><div class="up">Last updated: {UPDATED}</div>{body}
<footer>© 2026 {html.escape(_biz()["name"])} · <a href="/legal/contact">Contact</a></footer></main></body></html>"""
