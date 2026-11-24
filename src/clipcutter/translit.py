"""Devanagari Hindi -> Hinglish (Hindi in Roman letters, the way people type it on social media).

"भाई ये क्या हुआ" -> "bhai ye kya hua". Rule-based and free; good enough for captions:
- short spellings people actually use (ा -> a, ी -> i, ू -> u), long vowels only at a word start (आज -> aaj)
- the silent "a" at the end of words is dropped (अब -> ab, देख -> dekh)
- a common middle silent "a" is dropped too (करना -> karna)
"""
from __future__ import annotations

import re

CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
}
NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "फ": "f", "ड": "r", "ढ": "rh"}
PRECOMPOSED = {"क़": "क़", "ख़": "ख़", "ग़": "ग़", "ज़": "ज़", "ड़": "ड़", "ढ़": "ढ़", "फ़": "फ़"}
VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
          "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"}
MATRAS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
          "ॉ": "o", "ॅ": "e"}
VIRAMA, NUK, ANUS, CANDRA, VISARGA = "्", "़", "ं", "ँ", "ः"
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
# frequent words where rules miss the common spelling
COMMON = {"है": "hai", "हैं": "hain", "में": "mein", "मैं": "main", "नहीं": "nahi", "क्या": "kya", "भाई": "bhai",
          "यार": "yaar", "और": "aur", "तो": "toh", "यह": "yeh", "वह": "woh", "कि": "ki", "हाँ": "haan", "हां": "haan",
          "भी": "bhi", "ही": "hi", "जी": "ji", "गेम": "game", "वाला": "wala", "वाले": "wale", "वाली": "wali",
          "आप": "aap", "आज": "aaj", "बहुत": "bahut", "अच्छा": "accha", "क्यों": "kyun", "कैसे": "kaise",
          "दोस्तों": "doston", "गाइस": "guys", "ओके": "okay", "सो": "so", "बट": "but", "एंड": "and",
          # English words Hindi auto-captions write in Devanagari (common in gaming streams)
          "रॉकस्टार": "Rockstar", "पुलिस": "police", "मैप": "map", "प्ले": "play", "गेमप्ले": "gameplay",
          "लिटरली": "literally", "पब्लिक": "public", "डबल": "double", "इंपॉसिबल": "impossible", "स्ट्रीम": "stream",
          "चैनल": "channel", "वीडियो": "video", "मिशन": "mission", "कार": "car", "बाइक": "bike", "गन": "gun",
          "किल": "kill", "डेड": "dead", "रियल": "real", "रियलिस्टिक": "realistic", "ग्राफिक्स": "graphics",
          "फीचर": "feature", "फीचर्स": "features", "डिटेल": "detail", "डिटेल्स": "details", "प्लेयर": "player",
          "कैरेक्टर": "character", "स्टोरी": "story", "ओपन": "open", "वर्ल्ड": "world", "सिटी": "city",
          "एक्साइटमेंट": "excitement", "एक्साइटेड": "excited", "सीरियसली": "seriously", "ऑसम": "awesome",
          "इंसेन": "insane", "क्रेजी": "crazy", "रेडी": "ready", "लाइक": "like", "सब्सक्राइब": "subscribe",
          "कमेंट": "comment", "लाइव": "live", "चैट": "chat", "गाड़ी": "gaadi", "बड़ा": "bada", "बड़ी": "badi"}


def _word(w: str) -> str:
    if w in COMMON:
        return COMMON[w]
    for k, v in PRECOMPOSED.items():
        w = w.replace(k, v)
    units: list[list[str]] = []   # [consonant_or_vowel_roman, vowel_roman_or_None, is_consonant]
    i = 0
    while i < len(w):
        ch = w[i]
        if ch in CONS:
            c = CONS[ch]
            if i + 1 < len(w) and w[i + 1] == NUK:
                c = NUKTA.get(ch, c)
                i += 1
            units.append([c, "@", True])      # "@" = inherent vowel (pronounced "a" unless silent)
        elif ch in MATRAS and units and units[-1][2]:
            units[-1][1] = MATRAS[ch]
        elif ch == VIRAMA and units and units[-1][2]:
            units[-1][1] = ""
        elif ch in VOWELS:
            v = VOWELS[ch]
            units.append([v if not units else v.replace("aa", "a").replace("ee", "i").replace("oo", "u"), None, False])
        elif ch in (ANUS, CANDRA):
            if units:
                units[-1].append("n")
        elif ch == VISARGA:
            if units:
                units[-1].append("h")
        elif ch in DIGITS:
            units.append([DIGITS[ch], None, False])
        else:
            units.append([ch, None, False])
        i += 1
    # schwa deletion: final inherent "a", and middle "a" between vowel-carrying neighbours (karana -> karna)
    cons = [k for k, u in enumerate(units) if u[2]]
    if cons and units[-1][2] and units[-1][1] == "@" and len(units) > 1 and len(units[-1]) == 3:
        units[-1][1] = ""
    for k in range(1, len(units) - 1):
        u, prev, nxt = units[k], units[k - 1], units[k + 1]
        if (u[2] and u[1] == "@" and len(u) == 3 and nxt[2] and nxt[1]
                and ((prev[2] and prev[1]) or not prev[2])):
            u[1] = ""
    out = "".join(u[0] + (u[1] or "").replace("@", "a") + "".join(u[3:]) for u in units)
    out = re.sub(r"aa+", "aa", out)
    return out


def hinglish(text: str) -> str:
    """Convert every Devanagari word in text; leave Latin words, numbers and emoji as they are."""
    return re.sub(r"[ऀ-ॿ]+", lambda m: _word(m.group(0)), text)
