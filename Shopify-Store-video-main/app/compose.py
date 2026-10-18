"""Turn a fact sheet into a personalized email. AI when a key is set, templates otherwise."""
from __future__ import annotations

import json
import random
import re
import textwrap

import httpx

SYSTEM_PROMPT = """You write cold outreach emails for an independent creator who makes short product videos for small e-commerce brands.

Voice: how a real person types a quick message. Short sentences. Concrete nouns. No marketing voice.

Hard rules:
- Never invent facts. Only use details from the FACTS block. If something isn't there, don't mention it.
- Never say you bought, own, use or have tried the product. You're writing as a stranger who looked at their site.
- Never use placeholders like [Name], [Company], {product} or "insert X".
- No markdown, no bullets, no links, no emoji, no em dashes.
- Banned openers/phrases: "I hope this email finds you well", "I came across your website", "I wanted to reach out", "I am reaching out", "in today's fast-paced", "as a business owner", "I noticed that you", "elevate", "seamless", "leverage".
- Don't compliment vaguely ("amazing brand", "great products"). Compliments must point at a specific, checkable detail.
- Plain text email body, 70-120 words, plus a sign-off."""


def build_facts_block(facts: dict) -> str:
    """Compact, human-readable fact sheet for the prompt."""
    f = facts or {}
    lines: list[str] = []
    add = lambda k, v: lines.append(f"{k}: {v}") if v else None

    add("Store name", f.get("store_name"))
    add("Domain", f.get("domain"))
    add("Platform", f.get("platform"))
    add("Their own tagline", f.get("tagline"))
    add("Based in", f.get("location"))
    add("Founded", f.get("founded_year"))
    add("Founder", f.get("founder_name"))
    if f.get("top_tags"):
        add("Product tags", ", ".join(f["top_tags"][:8]))
    if f.get("product_types"):
        add("Product categories", ", ".join(f["product_types"]))
    if f.get("collections"):
        add("Collections", ", ".join(f["collections"][:6]))
    if f.get("price_range"):
        add("Price range", f["price_range"])
    if f.get("strong_signals"):
        add("Brand signals you may reference", "; ".join(f["strong_signals"]))
    elif f.get("signal_phrases"):
        add("Brand signals (background only, don't quote these back)", "; ".join(f["signal_phrases"]))
    if f.get("shipping_facts"):
        add("Shipping/returns", "; ".join(f["shipping_facts"]))
    if f.get("socials"):
        add("Socials", ", ".join(f"{k}: @{v}" for k, v in f["socials"].items()))

    prods = (f.get("products") or [])[:8]
    if prods:
        lines.append("Products (pick ONE of these to reference, by its exact title):")
        for p in prods:
            bits = [display_product(p.get("title", ""))]
            if p.get("price"):
                bits.append(f"({p.get('price')})")
            if p.get("type"):
                bits.append(f"[{p.get('type')}]")
            lines.append("  - " + " ".join(b for b in bits if b))

    if f.get("about_snippet"):
        lines.append("About page excerpt (verbatim, do not quote at length):")
        lines.append(textwrap.shorten(f["about_snippet"], width=600, placeholder=" ..."))
    elif f.get("home_snippet"):
        lines.append("Homepage excerpt:")
        lines.append(textwrap.shorten(f["home_snippet"], width=400, placeholder=" ..."))

    add("Privacy policy found", "yes" if f.get("privacy_policy_found") else "no")
    return "\n".join(lines)


def build_user_prompt(digest: str, settings: dict, store_hint: str, subject_hint: str) -> str:
    sender = settings.get("sender_name") or "the sender"
    company = settings.get("sender_company") or ""
    offer = settings.get("offer") or "makes short product videos for Shopify stores"
    video_line = settings.get("video_line") or "I already put together a short video for one of your products"
    cta = settings.get("cta") or "Want me to send it over?"
    tone = settings.get("tone") or "friendly, direct"
    subject_style = settings.get("subject_style") or "mix"

    optout = ""
    if settings.get("optout", True):
        optout = f'\n- End with this exact sentence on its own line after the sign-off: "{settings.get("optout_line")}"'

    company_line = f"\n- Sign off as {sender}{(' from ' + company) if company else ''}." if sender else ""

    return f"""FACTS about the store (this is all you know):
{digest}

WRITE ONE EMAIL.

Structure:
1. Greeting. Use the founder's first name only if a founder name is listed above; otherwise "Hi {store_hint} team," or "Hi there,".
2. One or two sentences that prove a human actually looked at their site: name a specific product, or a specific detail from their about page, their categories, or a brand signal. Be plain about it.
3. One sentence of who you are and what you do ({offer}).
4. One sentence framing the video: {video_line}. You have NOT sent it and there is NO link.
5. CTA: {cta}
6. Sign-off. Tone: {tone}.{company_line}{optout}

SUBJECT LINES: give exactly 3 options.
- Option 1: a short lowercase curiosity question about the store being active, in the spirit of "{subject_hint}". Keep it plain and a little blunt, e.g. "is <store> still running".
- Option 2: specific to the product or niche you referenced, also lowercase, under 7 words.
- Option 3: a plain spoken sentence-case question about the video, under 7 words.
Style note: {subject_style}.

Return ONLY valid JSON, no code fences:
{{"subjects": ["...", "...", "..."], "body": "...", "hook": "the exact detail you referenced", "angle": "3-6 word label"}}"""


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


async def compose_ai(facts: dict, settings: dict, store_hint: str = "the store") -> dict:
    """OpenAI-compatible chat completion. Raises on failure so the caller can fall back."""
    base = (settings.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    key = (settings.get("api_key") or "").strip()
    model = settings.get("model") or "gpt-4o-mini"
    if not key:
        raise RuntimeError("no API key")

    subject_hint = settings.get("subject_hint") or "is this store active"
    payload = {
        "model": model,
        "temperature": 0.85,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(build_facts_block(facts), settings, store_hint, subject_hint)},
        ],
    }
    if "api.groq.com" in base.lower() and model.lower().startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
        if r.status_code >= 400 and "response_format" in r.text:
            r = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("error", {}).get("message", "")
            except Exception:
                detail = r.text[:200]
            raise RuntimeError(f"API {r.status_code}: {detail or r.text[:160]}")

    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("unexpected API response shape")

    parsed = _parse_json(content)
    subjects = [re.sub(r"\s+", " ", str(s)).strip().strip('"') for s in (parsed.get("subjects") or []) if str(s).strip()]
    body = (parsed.get("body") or "").strip()
    if not body:
        raise RuntimeError("model returned no body")
    subjects = [s for s in subjects if 3 <= len(s) <= 90][:3]
    if not subjects:
        subjects = template_subjects(facts, settings)
    return {
        "subjects": subjects,
        "body": body,
        "hook": parsed.get("hook", ""),
        "angle": parsed.get("angle", ""),
        "engine": f"ai:{model}",
    }


async def test_api_key(settings: dict) -> dict:
    """Verify API access without requiring the model to follow the email JSON format."""
    base = (settings.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    key = (settings.get("api_key") or "").strip()
    model = settings.get("model") or "gpt-4o-mini"
    if not key:
        raise RuntimeError("No API key is configured.")

    payload = {
        "model": model,
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": "Reply with exactly: API key verified."},
        ],
    }
    if "api.groq.com" in base.lower() and model.lower().startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
    if response.status_code >= 400:
        try:
            error = response.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            error = response.text[:200]
        if key in error:
            error = error.replace(key, "[redacted]")
        raise RuntimeError(f"API {response.status_code}: {error or 'request failed'}")

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("API request succeeded, but the response had an unexpected format.")

    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("API request succeeded, but the model returned an empty response.")

    return {"engine": f"ai:{model}", "sample": content.strip()[:200]}


# ----------------------------------------------------------------- templates

def display_product(title: str, limit: int = 34) -> str:
    """"Men's Tree Skippers - Sesame (White Sole)" -> "Men's Tree Skippers" when it's too long."""
    t = (title or "").strip()
    if len(t) <= limit:
        return t
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)          # drop trailing "(White Sole)"
    t = re.sub(r"\s+[\u2013\u2014-]\s+.*$", "", t)   # drop " - Colourway"
    if len(t) > limit:
        t = t[:limit].rstrip(" ,;:-")
    return t or title.strip()


def short_store_name(facts: dict, max_words: int = 3, max_chars: int = 26) -> str:
    """'BROWN GIRL Jane Fine Fragrance' -> 'BROWN GIRL Jane' so subject lines stay short."""
    name = (facts.get("store_name") or facts.get("domain") or "your store").strip()
    name = re.sub(r"\s+(inc|llc|ltd|limited|co)\.?$", "", name, flags=re.I)
    name = re.sub(r"\s*[|·—–-]\s+.*$", "", name)  # strip "Store | Tagline" artefacts
    words = name.split()
    if len(words) > max_words:
        name = " ".join(words[:max_words])
    if len(name) > max_chars:
        name = " ".join(words[:2])
    return name.strip() or "your store"


def template_subjects(facts: dict, settings: dict, rng: random.Random | None = None) -> list[str]:
    rng = rng or random.Random()
    f = facts or {}
    name = (f.get("store_name") or f.get("domain") or "your store").strip()
    short = short_store_name(f)
    prods = f.get("products") or []
    product = display_product(prods[0]["title"]) if prods else ""
    hint = (settings.get("subject_hint") or "is this store active").strip()

    # 1) the blunt "is this store active" style
    if hint and hint.lower().startswith("is"):
        s1 = re.sub(r"\bthis store\b", short, hint, flags=re.I)
        if s1.lower() == hint.lower():
            s1 = f"{hint} ({short})"
    else:
        s1 = f"is {short} still active"
    out = [s1.replace("  ", " ").strip()]

    # 2) product-specific, product title kept verbatim
    if product:
        out.append(f"quick question about {product[:46].strip()}")
    elif f.get("product_types"):
        out.append(f"quick question about your {f['product_types'][0][:32].lower()}")
    else:
        out.append(f"one question about {short}")

    # 3) the video, plainly
    out.append(rng.choice([
        f"made a video for {short}",
        f"a video for {short}?",
        f"video idea for {short}",
    ]))

    seen, final = set(), []
    for s in out:
        s = re.sub(r"\s+", " ", s).strip().strip('"')
        if len(s) > 78:
            s = s[:75].rstrip(" ,;:-") + "..."
        k = s.lower()
        if k not in seen:
            seen.add(k)
            final.append(s[0].lower() + s[1:] if len(s) > 3 else s)
    return final[:3]


def template_body(facts: dict, settings: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    f = facts or {}
    store = (f.get("store_name") or f.get("domain") or "your store").strip()
    short = short_store_name(f)
    sender = (settings.get("sender_name") or "").strip()
    company = (settings.get("sender_company") or "").strip()

    prods = f.get("products") or []
    hero = prods[0] if prods else {}
    product = display_product(hero.get("title", ""))
    price = hero.get("price", "")
    currency = f.get("currency", "")
    if price:
        try:
            sym = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "C$", "AUD": "A$", "NGN": "₦", "INR": "₹"}.get(
                currency.upper(), ""
            )
            pv = float(price)
            price_txt = f"{sym}{int(pv) if pv == int(pv) else round(pv, 2)}"
        except (TypeError, ValueError):
            price_txt = ""
    else:
        price_txt = ""

    # Greeting
    founder_first = f.get("founder_first_name")
    if founder_first:
        greeting = rng.choice([f"Hi {founder_first},", f"Hey {founder_first},"])
    else:
        greeting = rng.choice([f"Hi {short} team,", f"Hi {short} team,", f"Hi there,", f"Hey {short} team,"])

    # Hook: the line that proves someone actually looked at the site
    hooks: list[str] = []
    # Only talk about price when it's clearly an entry-level item.
    price_is_entry = False
    if price_txt:
        try:
            pv = float(price)
            mx = 0.0
            for p in prods:
                try:
                    mx = max(mx, float(p.get("price") or 0))
                except (TypeError, ValueError):
                    pass
            price_is_entry = mx > 0 and pv <= min(120.0, mx * 0.7)
        except (TypeError, ValueError):
            price_is_entry = False
    if product and price_txt and price_is_entry:
        hooks.append(f"I ended up on {short} and {product} stopped me. {price_txt} for that is a sharp price point.")
        hooks.append(f"Was on {short} earlier and {product} is the one I kept coming back to.")
    elif product:
        hooks.append(f"I was on {short} earlier and {product} is the one that stuck with me.")
        hooks.append(f"{product} on your site is the product I kept looking at.")
    if f.get("collections"):
        hooks.append(f"Your {f['collections'][0].lower()} range is the bit I'd point at first.")
    # Story-based hooks only when we have real about-page prose and a signal that
    # reads naturally after "the fact that ...".
    strong = strong_signal_phrases_safe(f)
    if f.get("about_snippet") and strong:
        hooks.append(f"Read your about page. The fact that {strong[0]} is what stuck with me.")
        if len(strong) > 1:
            hooks.append(f"The fact that {strong[1]} is the part of your about page I'd lead with.")
    if f.get("product_types") and not f.get("collections"):
        t = f["product_types"][0].lower()
        hooks.append(f"Your {t} range is the thing I'd point at first if someone asked what {short} is about.")
    if not hooks:
        if f.get("location"):
            hooks.append(f"Had a look through {short} earlier. Saw you're based in {f['location'].split(',')[0]}.")
        else:
            hooks.append(f"Had a look through {short} this morning.")

    # Middle: who I am + the video tease
    offer = (settings.get("offer") or "I make short product videos for Shopify stores").rstrip(".")
    video_line = (settings.get("video_line") or "I already put together a short video for one of your products").rstrip(".")
    target = f" for {product}" if product else ""
    mids = [
        f"{offer}. I already put together a short one{target} to show you what I mean, it's about 20 seconds.",
        f"{offer}. I put together a short video{target} before emailing you, no strings.",
        f"{offer}. I made a quick example{target} so you can see the style rather than take my word for it.",
    ]
    if video_line and not any(video_line.lower()[:28] in m.lower() for m in mids):
        mids.append(video_line + f"{target}.")

    # CTA
    cta = (settings.get("cta") or "Want me to send it over?").strip()
    ctas = [cta, "Want me to send it over?", "Should I send it through?", "Worth a look?"]
    ctas = [c if c.endswith(("?", ".", "!")) else c + "?" for c in dict.fromkeys(ctas)]

    chosen_hook = rng.choice(hooks)
    parts = [greeting, chosen_hook, rng.choice(mids), rng.choice(ctas)]

    sign = sender or ""
    if company and sign:
        sign = f"{sign}\n{company}"
    elif company:
        sign = company
    if sign:
        parts.append(sign)

    optouts = [
        "Not interested? Just reply \"no\" and I won't follow up.",
        "If this isn't your thing, reply \"no\" and I'll leave you alone.",
        "Reply \"no\" if you'd rather not hear from me.",
    ]
    if settings.get("optout", True):
        line = (settings.get("optout_line") or rng.choice(optouts)).strip()
        if line:
            parts.append(line)

    body = "\n\n".join(p for p in parts if p)
    return {
        "subjects": template_subjects(f, settings, rng),
        "body": body,
        "hook": chosen_hook[:160],
        "angle": "template",
        "engine": "template",
    }


def strong_signal_phrases_safe(facts: dict) -> list[str]:
    """Phrases that read naturally after "the fact that ...". No crawler import needed."""
    phrases = facts.get("strong_signals") or []
    if phrases:
        return phrases
    # Fallback if the crawler didn't tag them: only trust unambiguous labels.
    safe = {
        "handmade", "small-batch", "family-run", "woman-owned", "Black-owned", "Latina-owned",
        "veteran-owned", "minority-owned", "B Corp", "carbon-neutral", "fair trade",
        "made in the USA", "made in the UK", "made in Canada", "made to order", "ships worldwide",
    }
    return [s for s in (facts.get("signals") or []) if s in safe]


def local_subject_for(facts: dict, settings: dict) -> str:
    return (template_subjects(facts, settings) or ["Quick question"])[0]


def safe_parse_json(raw: str | None) -> dict:
    """Coerce model output to a dict without raising for malformed payloads."""
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text, flags=re.I)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def contains_unsupported_claims(text: str | None) -> list[str]:
    text_norm = (text or "").lower()
    markers = [
        "guaranteed", "double sales", "doubles sales", "guaranteed to", "conversion", "viral",
        "best seller", "top seller", "abandoning carts", "tested and loved", "i purchased",
        "customers are leaving", "no one buys", "this product will definitely"
    ]
    hits = [marker for marker in markers if marker in text_norm]
    return hits


def _truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return bool(str(v).strip())


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_generated_output(payload: dict) -> dict:
    """Checks whether the generated offer stays grounded in evidence."""
    result = {
        "evidence_sufficient": False,
        "video_opportunity_found": False,
        "personalization_verified": False,
        "manual_review_required": False,
        "review_reasons": [],
    }
    diagnosis = payload.get("diagnosis") or {}
    store_profile = payload.get("store_profile") or {}
    product_selection = payload.get("product_selection") or {}
    video_brief = payload.get("video_brief") or {}
    outreach = payload.get("outreach") or {}

    observations = diagnosis.get("observations") or []
    if isinstance(observations, list) and observations:
        result["evidence_sufficient"] = True
    if not (store_profile.get("brand_name") or store_profile.get("store_url") or store_profile.get("niche")):
        result["review_reasons"].append("missing_store_profile")

    primary_opp = diagnosis.get("primary_opportunity") or ""
    if primary_opp:
        result["video_opportunity_found"] = True
    if not primary_opp and product_selection.get("product_name"):
        result["review_reasons"].append("product_without_credible_opportunity")

    if product_selection.get("product_name") and video_brief.get("format"):
        result["personalization_verified"] = bool(outreach.get("message") and outreach.get("subject"))
    if not outreach.get("message"):
        result["review_reasons"].append("missing_outreach_message")
    if not outreach.get("subject"):
        result["review_reasons"].append("missing_outreach_subject")

    message = (outreach.get("message") or "")
    claims = contains_unsupported_claims(message)
    if claims:
        result["review_reasons"].append("unsupported_claims")
    if claims or not result["evidence_sufficient"] or not result["video_opportunity_found"]:
        result["manual_review_required"] = True
    if result["review_reasons"]:
        result["manual_review_required"] = True
    result["review_reasons"] = [
        reason.replace("_", " ") for reason in dict.fromkeys(result["review_reasons"])
    ]
    if not primary_opp and not message:
        result["manual_review_required"] = True
    return result


def build_store_profile(facts: dict) -> dict:
    """Normalize extracted facts into a reusable profile."""
    f = facts or {}
    products = f.get("products") or []
    product_types = [
        str(item).strip() for item in (f.get("product_types") or [])
        if str(item).strip()
    ]
    collections = [
        str(item).strip() for item in (f.get("collections") or [])
        if str(item).strip()
    ]
    niche = ", ".join(product_types[:4] or collections[:4] or ["ecommerce products"])
    tagline = (f.get("tagline") or f.get("home_snippet") or "").strip()
    brand_name = (f.get("store_name") or "").strip() or (f.get("domain") or "").strip()
    location = (f.get("location") or "").strip()
    signals = [str(s).strip() for s in (f.get("signals") or []) if str(s).strip()]
    profile = {
        "brand_name": brand_name,
        "store_url": f.get("url") or f"https://{f.get('domain','')}",
        "niche": niche,
        "target_audience": f.get("target_audience") or "likely shoppers within the brand's core product category",
        "brand_positioning": tagline or f.get("tagline") or "Store positioning is not clearly stated but product and brand signals are available.",
        "brand_story": (f.get("about_snippet") or "").strip()[:500],
        "main_product_categories": product_types[:5] or collections[:5] or ["general product line"],
        "signals": signals[:8],
        "location": location,
        "has_product_data": bool(products),
        "has_about_page": bool((f.get("about_snippet") or "").strip()),
        "has_video_evidence": bool(f.get("video_assets") or f.get("socials") or f.get("video_embeds")),
    }
    return profile


def diagnose_video_opportunity(facts: dict, store_profile: dict | None = None) -> dict:
    """Assess whether a product or brand has a credible video opportunity grounded in accessible evidence."""
    f = facts or {}
    profile = store_profile or build_store_profile(f)
    products = f.get("products") or []
    observations = []
    primary_opp = ""
    reason = ""
    confidence = 0.0
    limitations = []

    static_image_count = sum(1 for p in products if not p.get("image"))
    if products and static_image_count >= max(1, len(products) // 2):
        observations.append({
            "finding": "Several featured products are shown without clear demonstration media or product-in-use visuals.",
            "source_url": f.get("url") or profile.get("store_url") or "",
            "evidence_type": "observed",
            "confidence": 0.78,
        })
        primary_opp = "Product operation or usage is difficult to understand"
        reason = "The storefront emphasizes product images but not direct product demonstration, which can leave buyers unsure how it works or how it feels in real life."
        confidence = 0.8

    if not products:
        limitations.append("No product data was extracted from the store.")

    about_text = (f.get("about_snippet") or "").strip()
    has_visual_media = any(bool(p.get("image")) for p in products)
    if about_text and len(about_text) < 180 and not has_visual_media:
        observations.append({
            "finding": "The brand story is brief and does not provide much context for a founder or product-use story.",
            "source_url": f.get("url") or profile.get("store_url") or "",
            "evidence_type": "inferred",
            "confidence": 0.55,
        })
        if not primary_opp:
            primary_opp = "A founder story or brand purpose could provide useful context"
            reason = "The brand has a limited story footprint and a short brand narrative could help make the product feel more tangible."
            confidence = 0.58

    if (
        f.get("home_snippet") and "install" in (f.get("home_snippet") or "").lower()
        and products and not has_visual_media
    ):
        observations.append({
            "finding": "The product page or homepage mentions installation or usage details but does not appear to show them in motion.",
            "source_url": f.get("url") or profile.get("store_url") or "",
            "evidence_type": "observed",
            "confidence": 0.7,
        })
        if not primary_opp:
            primary_opp = "Product use or practical application is unclear"
            reason = "The site describes use or installation but does not visibly demonstrate the product in context."
            confidence = 0.72

    if not primary_opp and profile.get("has_about_page"):
        limitations.append("The site already presents its products reasonably well and there is no strong evidence of a missing demonstration format.")

    if not observations:
        limitations.append("No strong evidence of a missing demonstration or story angle was found.")

    return {
        "primary_opportunity": primary_opp,
        "observations": observations[:5],
        "reason_video_may_help": reason,
        "limitations": limitations,
        "confidence": round(confidence, 2),
        "recommended_format": (
            "product demonstration" if primary_opp else ""
        ),
    }


def score_product_candidate(product: dict, profile: dict, diagnosis: dict) -> dict:
    """Apply a 10-point heuristic to estimate how suitable a product is for a video opportunity."""
    p = product or {}
    title = str(p.get("title") or "").strip()
    description = str(p.get("description") or "").strip()
    product_type = str(p.get("type") or "").strip()
    evidence_gap = 0
    video_fit = 0
    demo_potential = 0
    brand_fit = 0
    content_gap = 0

    if not title:
        return {"score": 0, "score_breakdown": {"evidence_gap": 0, "video_fit": 0, "demo_potential": 0, "brand_fit": 0, "content_gap": 0}}

    if not p.get("image"):
        evidence_gap += 3
    elif len(description) < 80:
        evidence_gap += 1
    else:
        evidence_gap += 2

    if diagnosis.get("primary_opportunity"):
        video_fit += 3
        if "operation" in (diagnosis.get("primary_opportunity") or "").lower() or "usage" in (diagnosis.get("primary_opportunity") or "").lower():
            video_fit += 1
    if product_type and product_type.lower() in [item.lower() for item in profile.get("main_product_categories", [])]:
        brand_fit += 1
    if description and any(
        word in description.lower()
        for word in ["fit", "size", "material", "how to", "install", "use", "apply", "works"]
    ):
        demo_potential += 2
    elif description:
        demo_potential += 1
    if not p.get("image") or len(description) < 100:
        content_gap += 1

    total = min(10, evidence_gap + video_fit + demo_potential + brand_fit + content_gap)
    breakdown = {
        "evidence_backed_product_or_presentation_gap": evidence_gap,
        "suitability_of_video_for_gap": video_fit,
        "visual_demonstration_potential": demo_potential,
        "fit_with_brand_positioning_and_customer": brand_fit,
        "opportunity_to_improve_on_existing_video_content": content_gap,
    }
    return {"score": total, "score_breakdown": breakdown}


def pick_primary_product(facts: dict, store_profile: dict, diagnosis: dict) -> dict:
    products = facts.get("products") or []
    if not products:
        return {
            "product_name": "",
            "product_url": "",
            "selection_reason": "No product data was available for convincing selection.",
            "score": 0,
            "score_breakdown": {},
            "alternative_candidates": [],
        }

    ranked = []
    for product in products:
        scored = score_product_candidate(product, store_profile, diagnosis)
        ranked.append({
            "product": product,
            "score": scored["score"],
            "score_breakdown": scored["score_breakdown"],
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    primary = ranked[0]
    alternatives = [
        {"product_name": str(item["product"].get("title") or ""), "score": item["score"]}
        for item in ranked[1:4]
        if item["product"].get("title")
    ]
    product = primary["product"]
    selection_reason = "The product best reflects the identified gap and has the clearest visual demonstration opportunity."
    if primary["score"] < 5:
        selection_reason = "The evidence is too weak to justify a high-confidence product pick without further review."
    return {
        "product_name": str(product.get("title") or ""),
        "product_url": str(product.get("url") or ""),
        "selection_reason": selection_reason,
        "score": primary["score"],
        "score_breakdown": primary["score_breakdown"],
        "alternative_candidates": alternatives,
    }


def build_video_brief(facts: dict, store_profile: dict, diagnosis: dict, product: dict, settings: dict | None = None) -> dict:
    product_name = str(product.get("title") or "").strip()
    product_url = str(product.get("url") or facts.get("url") or "").strip()
    opportunity = diagnosis.get("primary_opportunity") or ""
    if not opportunity:
        return {
            "format": "",
            "objective": "",
            "duration_seconds": 0,
            "hook": "",
            "scenes": [],
            "key_benefit": "",
            "cta": "",
            "restrictions": [],
        }

    format_name = diagnosis.get("recommended_format") or "product demonstration"
    objective = "Show how the product is used and why it matters in a real-world context without making unsupported claims."
    hook = f"{product_name} in use"
    scenes = [
        "Open with a close shot of the product in context",
        "Show the key motion, setup, or usage step in plain view",
        "Highlight the specific practical benefit the customer needs to understand",
        "End with a clean, branded close and a simple call to action",
    ]
    restrictions = [
        "Do not claim performance outcomes that are not directly supported by the site or product copy.",
        "Use only available product imagery and copy as the visual reference.",
    ]
    return {
        "format": format_name,
        "objective": objective,
        "duration_seconds": 20,
        "hook": hook,
        "scenes": scenes,
        "key_benefit": "A clearer product-use explanation that reduces uncertainty before a purchase.",
        "cta": "See how it works in real use.",
        "restrictions": restrictions,
        "brand_and_product": {
            "brand_name": store_profile.get("brand_name"),
            "product_name": product_name,
            "product_url": product_url,
        },
    }


def generate_outreach_message(facts: dict, store_profile: dict, diagnosis: dict, product: dict, settings: dict | None = None) -> dict:
    product_name = str(product.get("title") or "").strip()
    brand_name = store_profile.get("brand_name") or facts.get("store_name") or "your store"
    if not diagnosis.get("primary_opportunity") or not product_name:
        return {"subject": "", "message": ""}

    subject = f"quick idea for {product_name}"
    message = (
        f"Hi there,\n\n"
        f"I was looking through {brand_name} and {product_name} stood out as a strong fit for a short product demonstration. "
        f"The product feels like a good candidate for a quick proof-of-use video because the main value is easier to understand when people can see it in action.\n\n"
        f"I make short videos for Shopify brands that help explain how a product works, where it fits in everyday use, and what makes it feel premium without sounding overproduced. "
        f"I think a 15 to 25 second demo could make the product feel clearer and more tangible for shoppers.\n\n"
        f"If it makes sense, I can put together a concept and send over a rough idea for your review."
    )
    return {"subject": subject, "message": message}


def compose_store_intelligence(facts: dict, settings: dict | None = None) -> dict:
    """Build the new evidence-based store intelligence workflow while preserving old behavior elsewhere."""
    f = facts or {}
    settings = settings or {}
    profile = build_store_profile(f)
    diagnosis = diagnose_video_opportunity(f, profile)
    product = ((f.get("products") or [])[0] if (f.get("products") or []) else {})
    selection = pick_primary_product(f, profile, diagnosis)
    if selection.get("product_name"):
        product_candidates = (f.get("products") or [])
        for candidate in product_candidates:
            if str(candidate.get("title") or "") == selection.get("product_name"):
                product = candidate
                break
    video_brief = build_video_brief(f, profile, diagnosis, product, settings)
    outreach = generate_outreach_message(f, profile, diagnosis, product, settings)

    if not diagnosis.get("primary_opportunity") or not product.get("title"):
        video_brief = {"format": "", "objective": "", "duration_seconds": 0, "hook": "", "scenes": [], "key_benefit": "", "cta": "", "restrictions": []}
        outreach = {"subject": "", "message": ""}

    output = {
        "store_profile": profile,
        "diagnosis": {
            "primary_opportunity": diagnosis.get("primary_opportunity") or "",
            "observations": diagnosis.get("observations") or [],
            "reason_video_may_help": diagnosis.get("reason_video_may_help") or "",
            "limitations": diagnosis.get("limitations") or [],
            "confidence": diagnosis.get("confidence") or 0.0,
        },
        "product_selection": selection,
        "video_brief": video_brief,
        "outreach": outreach,
    }
    output["quality_control"] = validate_generated_output(output)
    return output


async def compose(facts: dict, settings: dict, store_hint: str = "the store") -> dict:
    """AI if possible, template if not. Always returns something usable."""
    if settings.get("use_ai", True) and (settings.get("api_key") or "").strip():
        try:
            return await compose_ai(facts, settings, store_hint)
        except Exception as e:  # noqa: BLE001 - any failure falls back to templates
            out = template_body(facts, settings)
            out["engine"] = "template"
            out["fallback_reason"] = str(e)[:200]
            return out
    return template_body(facts, settings)
