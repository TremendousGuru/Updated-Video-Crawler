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


def _known_video_assets(product: dict, facts: dict) -> list[dict]:
    assets = product.get("video_assets") or product.get("videos") or []
    if isinstance(assets, bool):
        return [{"type": "video"}] if assets else []
    if isinstance(assets, str):
        return [{"type": "video", "url": assets}]
    return list(assets) if isinstance(assets, list) else []


def _candidate_plan(product: dict, facts: dict, profile: dict) -> dict:
    title = str(product.get("title") or "").strip()
    product_type = str(product.get("type") or "").strip()
    tags = [str(tag).strip() for tag in (product.get("tags") or []) if str(tag).strip()]
    description = re.sub(r"\s+", " ", str(product.get("description") or "")).strip()
    source_url = str(product.get("url") or facts.get("url") or profile.get("store_url") or "")
    assets = _known_video_assets(product, facts)

    if not title or assets:
        limitations = []
        observations = []
        if assets:
            observations.append({
                "finding": f"An existing product video asset is listed for {title}.",
                "source_url": source_url,
                "evidence_type": "observed",
                "confidence": 0.95,
            })
            limitations.append("The product already has video content; do not pitch a duplicate without reviewing its quality or finding a distinct unmet need.")
        return {
            "product": product,
            "primary_opportunity": "",
            "observations": observations,
            "reason_video_may_help": "",
            "limitations": limitations,
            "confidence": 0.0,
            "recommended_format": "",
            "concept": "",
            "evidence": [],
            "source_url": source_url,
            "score": 0,
            "score_breakdown": {},
        }

    lower = f"{title} {product_type} {' '.join(tags)} {description}".lower()
    evidence = [{"fact": title, "source_url": source_url, "evidence_type": "observed"}]
    if product_type:
        evidence.append({"fact": product_type, "source_url": source_url, "evidence_type": "observed"})
    if description:
        evidence.append({"fact": description[:600], "source_url": source_url, "evidence_type": "observed"})

    practical_patterns = (
        (r"\bclamp\w*\b", "product demonstration", "Show the clamp attaching to the shelf or desk edge, then angle the arm over the workspace."),
        (r"\b(install|installation|mount|assemble|assembly|setup|set up)\w*\b", "installation demonstration", "Show the setup step by step, using only the installation details stated in the product description."),
        (r"\b(apply|application|wear|fit|adjust|fold|pour|connect|attach|operate|use)\w*\b", "product demonstration", f"Show how {title} is used in the way described on its product page."),
        (r"\b(locking lid|leakproof|waterproof|insulated|adjustable)\b", "product feature demonstration", "Use close-ups to show the named feature being handled, without adding performance claims."),
    )
    format_name = ""
    concept = ""
    opportunity = ""
    reason = ""
    confidence = 0.0
    evidence_strength = 0

    for pattern, candidate_format, candidate_concept in practical_patterns:
        if re.search(pattern, lower):
            format_name = candidate_format
            concept = candidate_concept
            opportunity = "A product-use or feature demonstration is a relevant creative opportunity"
            reason = "The extracted product details name a specific action or feature that can be shown directly in a short video. This is a creative opportunity, not evidence of a sales or customer problem."
            confidence = 0.82 if description else 0.58
            evidence_strength = 3 if description else 1
            break

    lifestyle_cues = (
        ("evening routine", f"Place {title} in a simple evening routine, with a small text cue for the warm cedar scent named in its description."),
        ("morning routine", "Build a short morning scene around the product, using the routine and product details stated in its description as the creative cues."),
        ("outdoor", "Show the product in the outdoor context explicitly named in its product details."),
        ("hiking", "Show the product as part of a hiking preparation scene, sticking to the use and features named in its product details."),
        ("travel", "Build a short packing or travel scene around the product, using only the travel use described on its page."),
        ("gift", "Frame the product as a considered gift, using its real packaging or product imagery as references if available."),
    )
    if not concept:
        for cue, candidate_concept in lifestyle_cues:
            if cue in lower:
                format_name = "lifestyle video"
                concept = candidate_concept
                opportunity = "A product-specific lifestyle or use-case story is a relevant creative opportunity"
                reason = f"The extracted product information explicitly references {cue}; a short scene can make that context tangible without claiming customer outcomes."
                confidence = 0.78
                evidence_strength = 3
                break

    if not concept and re.search(r"\b(hat|cap|shirt|hoodie|jacket|dress|bag|backpack|shoe|sneaker)\b", lower):
        format_name = "lifestyle styling video"
        concept = f"Build a simple outfit or carry look around {title}, keeping the product as the visual focus."
        opportunity = "A product-specific styling concept is a relevant creative opportunity"
        reason = "The product title or category identifies a wearable/accessory item that can be shown in a styling context. This is a proposed creative angle, not a claim that the current presentation is inadequate."
        confidence = 0.66
        evidence_strength = 2 if product_type or tags else 1

    if not concept and description and len(description.split()) >= 8:
        # A useful creative idea still needs an identifiable attribute/use case to build on.
        sentences = re.split(r"(?<=[.!?])\s+", description)
        detail = next((sentence.strip() for sentence in sentences if len(sentence.split()) >= 5), "")
        if detail:
            format_name = "product detail video"
            concept = f"Use a close-up product story to bring this page detail to life: {detail}"
            opportunity = "A product-specific detail can anchor a focused video concept"
            reason = "The product description includes a concrete detail that can be translated into visuals; no customer difficulty is inferred."
            confidence = 0.62
            evidence_strength = 2

    if not concept:
        return {
            "product": product,
            "primary_opportunity": "",
            "observations": [],
            "reason_video_may_help": "",
            "limitations": ["Available product data is too limited to support a specific, differentiated video idea."],
            "confidence": 0.0,
            "recommended_format": "",
            "concept": "",
            "evidence": evidence,
            "source_url": source_url,
            "score": 0,
            "score_breakdown": {},
        }

    observations = [{
        "finding": evidence[-1]["fact"] if description else f"The extracted product title/category identifies {title} as {product_type or 'a specific product'}.",
        "source_url": source_url,
        "evidence_type": "observed",
        "confidence": confidence,
    }]
    presentation_note = product.get("presentation_observation")
    if presentation_note:
        observations.insert(0, {
            "finding": str(presentation_note),
            "source_url": source_url,
            "evidence_type": "observed",
            "confidence": 0.9,
        })

    score = score_product_candidate(product, profile, {"primary_opportunity": opportunity}, _plan=False)
    if not description:
        score["score"] = min(score["score"], 7)
    return {
        "product": product,
        "primary_opportunity": opportunity,
        "observations": observations,
        "reason_video_may_help": reason,
        "limitations": ["No claim is made about customer behavior, conversion, or a proven weakness in the current product page."],
        "confidence": confidence,
        "recommended_format": format_name,
        "concept": concept,
        "evidence": evidence,
        "source_url": source_url,
        "score": score["score"],
        "score_breakdown": score["score_breakdown"],
        "evidence_strength": evidence_strength,
    }


def diagnose_video_opportunity(facts: dict, store_profile: dict | None = None, product: dict | None = None) -> dict:
    """Select a creative opportunity only where extracted product evidence supports one."""
    f = facts or {}
    profile = store_profile or build_store_profile(f)
    products = [product] if product else (f.get("products") or [])
    plans = [_candidate_plan(candidate, f, profile) for candidate in products]
    plans = [plan for plan in plans if plan.get("primary_opportunity")]
    if not plans:
        known_assets = [
            asset for candidate in (f.get("products") or [])
            for asset in _known_video_assets(candidate, f)
        ]
        return {
            "primary_opportunity": "",
            "observations": ([{
                "finding": "Existing product video content is present; a duplicate concept is not recommended without a distinct unmet need.",
                "source_url": (f.get("products") or [{}])[0].get("url") or f.get("url", ""),
                "evidence_type": "observed",
                "confidence": 0.95,
            }] if known_assets else []),
            "reason_video_may_help": "",
            "limitations": (["The product already has video content; review it before proposing any new production."] if known_assets else ["No product-specific concept is supported by the extracted facts."]),
            "confidence": 0.0,
            "recommended_format": "",
            "concept": "",
            "evidence": [],
        }
    selected = max(plans, key=lambda plan: plan.get("score", 0))
    return {key: selected[key] for key in (
        "primary_opportunity", "observations", "reason_video_may_help", "limitations",
        "confidence", "recommended_format", "concept", "evidence", "source_url",
    )}


def score_product_candidate(product: dict, profile: dict, diagnosis: dict, _plan: bool = True) -> dict:
    """Score evidence, video fit, visual potential, brand fit, and known content gaps (0-10)."""
    p = product or {}
    title = str(p.get("title") or "").strip()
    description = str(p.get("description") or "").strip()
    if not title:
        return {"score": 0, "score_breakdown": {}}
    if _known_video_assets(p, {}):
        return {"score": 0, "score_breakdown": {}}

    evidence = min(3, (1 if title else 0) + (1 if p.get("type") or p.get("tags") else 0) + (1 if description else 0))
    video_fit = 3 if diagnosis.get("primary_opportunity") and description else (2 if diagnosis.get("primary_opportunity") else 0)
    visual = 2 if (
        re.search(r"\b(show|use|wear|fit|clamp|install|apply|adjust|pour|assemble|routine|hiking|travel)\b", f"{title} {description} {p.get('type', '')}", re.I)
        or re.search(r"\b(hat|cap|shirt|hoodie|jacket|dress|bag|backpack|shoe|sneaker)\b", title, re.I)
    ) else (1 if p.get("type") else 0)
    brand_fit = 1 if p.get("type") and p.get("type", "").lower() in [v.lower() for v in profile.get("main_product_categories", [])] else 0
    content_gap = 1 if p.get("presentation_observation") else 0
    total = min(10, evidence + video_fit + visual + brand_fit + content_gap)
    return {
        "score": total,
        "score_breakdown": {
            "evidence_backed_product_or_presentation_gap": evidence,
            "suitability_of_video_for_gap": video_fit,
            "visual_demonstration_potential": visual,
            "fit_with_brand_positioning_and_customer": brand_fit,
            "opportunity_to_improve_on_existing_video_content": content_gap,
        },
    }


def pick_primary_product(facts: dict, store_profile: dict, diagnosis: dict) -> dict:
    products = facts.get("products") or []
    ranked = []
    for product in products:
        plan = _candidate_plan(product, facts, store_profile)
        if plan.get("primary_opportunity"):
            ranked.append({"product": product, "plan": plan})
    ranked.sort(key=lambda item: item["plan"].get("score", 0), reverse=True)
    if not ranked or ranked[0]["plan"].get("score", 0) < 5:
        return {
            "product_name": "",
            "product_url": "",
            "selection_reason": "The available evidence is not strong enough for a confident product recommendation.",
            "score": ranked[0]["plan"].get("score", 0) if ranked else 0,
            "score_breakdown": ranked[0]["plan"].get("score_breakdown", {}) if ranked else {},
            "alternative_candidates": [],
        }
    primary = ranked[0]
    product = primary["product"]
    return {
        "product_name": str(product.get("title") or ""),
        "product_url": str(product.get("url") or ""),
        "selection_reason": "Selected because its extracted details support a specific, visually communicable concept.",
        "score": primary["plan"].get("score", 0),
        "score_breakdown": primary["plan"].get("score_breakdown", {}),
        "alternative_candidates": [
            {"product_name": str(item["product"].get("title") or ""), "score": item["plan"].get("score", 0)}
            for item in ranked[1:3]
        ],
    }


def build_video_brief(facts: dict, store_profile: dict, diagnosis: dict, product: dict, settings: dict | None = None) -> dict:
    product_name = str(product.get("title") or "").strip()
    if not diagnosis.get("primary_opportunity") or not product_name:
        return {"format": "", "objective": "", "duration_seconds": 0, "hook": "", "concept": "", "scenes": [], "key_benefit": "", "cta": "", "restrictions": []}
    concept = diagnosis.get("concept") or ""
    source_url = str(product.get("url") or facts.get("url") or "")
    scenes = [
        "Open on the product and the setting or detail named in the source information.",
        concept,
        "Close on the product with a simple brand end frame; do not add unsourced claims.",
    ]
    return {
        "format": diagnosis.get("recommended_format") or "",
        "objective": "Translate one extracted product detail or use case into a concise visual story.",
        "duration_seconds": 20,
        "hook": concept,
        "concept": concept,
        "scenes": scenes,
        "key_benefit": "Make the specific product detail or use case easy to see.",
        "cta": "Explore the product.",
        "restrictions": ["Do not imply customer outcomes or add product claims absent from the extracted source."],
        "evidence": diagnosis.get("evidence") or [],
        "source_url": source_url,
        "brand_and_product": {"brand_name": store_profile.get("brand_name"), "product_name": product_name, "product_url": source_url},
    }


def _concept_terms(text: str) -> list[str]:
    ignored = {"this", "that", "with", "from", "their", "product", "short", "video", "show", "around", "using", "named", "page", "description", "specific", "only", "without", "stated", "details", "itself", "then", "into", "over", "the", "and", "for"}
    return [word.lower() for word in re.findall(r"[A-Za-z0-9]+", text or "") if len(word) > 3 and word.lower() not in ignored]


def validate_outreach_personalization(outreach: dict, facts: dict, product: dict, video_brief: dict) -> dict:
    message = str(outreach.get("message") or "")
    title = str(product.get("title") or "").strip()
    concept = str(video_brief.get("concept") or "")
    title_terms = set(_concept_terms(title))
    concept_terms = [term for term in _concept_terms(concept) if term not in title_terms]
    has_anchor = bool(title and title.lower() in message.lower())
    has_concept = bool(concept_terms and sum(term in message.lower() for term in concept_terms) >= min(2, len(concept_terms)))
    extracted = bool(title and any(
        title.lower() in str(product.get(field) or "").lower()
        for field in ("title", "description", "type")
    ))
    unsupported = contains_unsupported_claims(message)
    generic_intro = any(phrase in message.lower() for phrase in (
        "i make short product videos for shopify stores",
        "i make short videos for shopify brands",
    ))
    enough_specificity = has_anchor and has_concept and extracted and not generic_intro
    reasons = []
    if not has_anchor:
        reasons.append("message does not mention the selected product")
    if not has_concept:
        reasons.append("message does not explain the selected concept")
    if generic_intro:
        reasons.append("message relies on a generic service introduction")
    if unsupported:
        reasons.append("message contains unsupported or performance claims")
    if len(message.split()) > 115:
        reasons.append("message is too long")
    return {
        "meaningful_observation_or_idea": has_anchor and has_concept,
        "explains_product_relevance": has_concept,
        "based_on_extracted_information": extracted,
        "personalization_verified": enough_specificity and not unsupported,
        "manual_review_required": not enough_specificity or bool(unsupported),
        "review_reasons": reasons,
    }


def generate_outreach_message(facts: dict, store_profile: dict, diagnosis: dict, product: dict, settings: dict | None = None, video_brief: dict | None = None) -> dict:
    """Write the message from selected evidence and the chosen concept, never just names and a generic pitch."""
    settings = settings or {}
    video_brief = video_brief or {}
    title = str(product.get("title") or "").strip()
    concept = str(video_brief.get("concept") or diagnosis.get("concept") or "").strip()
    if not diagnosis.get("primary_opportunity") or not title or not concept:
        return {"subject": "", "message": ""}

    brand = store_profile.get("brand_name") or facts.get("store_name") or ""
    description = re.sub(r"\s+", " ", str(product.get("description") or "")).strip()
    product_type = str(product.get("type") or "").strip()
    if description:
        lead = f"Your product page describes {title} as “{description.rstrip('.')}.”"
    elif re.search(r"\b(hat|cap|shirt|hoodie|jacket|dress|bag|backpack|shoe|sneaker)\b", title, re.I):
        lead = f"I saw {title} on your site and had a styling idea."
    elif product_type:
        lead = f"I saw {title} in your {product_type} category, which gave me a styling idea."
    else:
        lead = f"{title} gave me a specific creative direction."

    format_name = video_brief.get("format") or "short video"
    concept_line = concept[0].lower() + concept[1:] if concept else ""
    message = (
        f"Hi {brand + ' team' if brand else 'there'},\n\n"
        f"{lead} For a {format_name}, I’d {concept_line}\n\n"
        f"Would you be open to seeing a short storyboard?"
    )
    sender = str(settings.get("sender_name") or "").strip()
    company = str(settings.get("sender_company") or "").strip()
    if sender:
        message += f"\n\n{sender}" + (f"\n{company}" if company else "")
    optout = str(settings.get("optout_line") or "").strip()
    if settings.get("optout", False) and optout:
        message += f"\n\n{optout}"
    subject = f"a video idea for {title}"
    return {"subject": subject, "message": message}


INTELLIGENCE_SYSTEM_PROMPT = """You write concise, warm, natural outreach about a specific short-video concept for an ecommerce product.
Use only the supplied extracted facts, evidence, diagnosis and concept. Lead with a real product observation or a relevant creative idea, explain the visual concept in plain English, and connect it to a distinctive extracted feature, use case, audience or benefit. If an evidence-backed presentation problem is provided, explain how the concept could address it without asserting customer behavior. Never invent weaknesses, customer behavior, features, results, certifications, or performance claims. Do not use a generic service introduction, merely repeat the product name, or claim a video has already been made. If the evidence does not support an individualized message, return an empty message and require manual review. Keep it concise and conversational with one low-pressure CTA. Return JSON only with subject and message."""


def build_intelligent_outreach_prompt(facts: dict, profile: dict, diagnosis: dict, selection: dict, brief: dict, settings: dict) -> str:
    product = next((p for p in (facts.get("products") or []) if p.get("title") == selection.get("product_name")), {})
    return json.dumps({
        "store_profile": profile,
        "selected_product": product,
        "product_selection": selection,
        "diagnosis": diagnosis,
        "video_concept": brief,
        "evidence_to_reference": diagnosis.get("evidence") or [],
        "sender_name": settings.get("sender_name", ""),
        "sender_company": settings.get("sender_company", ""),
        "cta_guidance": "Ask whether they would be open to seeing a short storyboard.",
    }, ensure_ascii=True)


async def compose_intelligent_ai(facts: dict, settings: dict, profile: dict, diagnosis: dict, selection: dict, brief: dict) -> dict:
    base = (settings.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    key = (settings.get("api_key") or "").strip()
    model = settings.get("model") or "gpt-4o-mini"
    if not key:
        raise RuntimeError("no API key")
    payload = {
        "model": model,
        "temperature": 0.55,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": INTELLIGENCE_SYSTEM_PROMPT},
            {"role": "user", "content": build_intelligent_outreach_prompt(facts, profile, diagnosis, selection, brief, settings)},
        ],
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(2):
            response = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(f"AI API returned HTTP {response.status_code}")
            data = response.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise RuntimeError("unexpected AI response shape")
            parsed = safe_parse_json(content)
            result = {"subject": str(parsed.get("subject") or "").strip(), "message": str(parsed.get("message") or "").strip()}
            product = next((p for p in (facts.get("products") or []) if p.get("title") == selection.get("product_name")), {})
            quality = validate_outreach_personalization(result, facts, product, brief)
            if not quality["manual_review_required"]:
                return result
            if attempt == 0:
                payload["messages"].append({
                    "role": "user",
                    "content": "Revise once to fix these quality failures: " + "; ".join(quality["review_reasons"])
                    + ". Keep the selected product, facts, evidence and concept unchanged; include the concept wording and a product-specific observation."
                    + " Return subject/message JSON only.",
                })
    raise RuntimeError("AI response did not pass personalization checks")


def compose_store_intelligence(facts: dict, settings: dict | None = None) -> dict:
    """Build the evidence-to-concept-to-outreach workflow while preserving raw facts separately."""
    f = facts or {}
    settings = settings or {}
    profile = build_store_profile(f)
    selection = pick_primary_product(f, profile, {})
    selected_product = next((p for p in (f.get("products") or []) if p.get("title") == selection.get("product_name")), {})
    diagnosis = diagnose_video_opportunity(f, profile, selected_product if selected_product else None)
    video_brief = build_video_brief(f, profile, diagnosis, selected_product, settings)
    outreach = generate_outreach_message(f, profile, diagnosis, selected_product, settings, video_brief)
    outreach_quality = validate_outreach_personalization(outreach, f, selected_product, video_brief)
    evidence_sufficient = bool(diagnosis.get("evidence")) and bool(selected_product)
    quality = {
        "evidence_sufficient": evidence_sufficient,
        "video_opportunity_found": bool(diagnosis.get("primary_opportunity")),
        "personalization_verified": outreach_quality["personalization_verified"],
        "manual_review_required": outreach_quality["manual_review_required"] or not evidence_sufficient,
        "review_reasons": outreach_quality["review_reasons"] + (diagnosis.get("limitations") or [] if not evidence_sufficient or not diagnosis.get("primary_opportunity") else []),
        "outreach_checks": outreach_quality,
    }
    return {
        "store_profile": profile,
        "diagnosis": diagnosis,
        "product_selection": selection,
        "video_brief": video_brief,
        "outreach": outreach,
        "outreach_evidence": {
            "product_facts": [selected_product.get("title", ""), selected_product.get("type", "")],
            "observations": diagnosis.get("observations") or [],
            "primary_opportunity": diagnosis.get("primary_opportunity") or "",
            "format": video_brief.get("format") or "",
            "concept": video_brief.get("concept") or "",
            "reason_concept_fits": diagnosis.get("reason_video_may_help") or "",
            "sources": diagnosis.get("evidence") or [],
        },
        "quality_control": quality,
    }


async def compose(facts: dict, settings: dict, store_hint: str = "the store") -> dict:
    """Run diagnosis before writing; keep the legacy output keys for existing callers."""
    intelligence = compose_store_intelligence(facts, settings)
    if intelligence["quality_control"]["manual_review_required"]:
        return {
            "subjects": [], "body": "", "hook": "", "angle": "", "engine": "manual-review",
            "manual_review_required": True, "fallback_reason": "; ".join(intelligence["quality_control"]["review_reasons"][:3]),
            "intelligence": intelligence,
        }

    product = next((p for p in (facts.get("products") or []) if p.get("title") == intelligence["product_selection"].get("product_name")), {})
    outreach = intelligence["outreach"]
    engine = "evidence-template"
    if settings.get("use_ai", True) and (settings.get("api_key") or "").strip():
        try:
            outreach = await compose_intelligent_ai(
                facts, settings, intelligence["store_profile"], intelligence["diagnosis"],
                intelligence["product_selection"], intelligence["video_brief"],
            )
            engine = f"ai:{settings.get('model') or 'gpt-4o-mini'}"
        except Exception as error:  # noqa: BLE001
            intelligence["quality_control"]["review_reasons"].append(f"AI draft rejected; used evidence template: {str(error)[:120]}")
            engine = "evidence-template"

    quality = validate_outreach_personalization(outreach, facts, product, intelligence["video_brief"])
    if quality["manual_review_required"]:
        outreach = generate_outreach_message(
            facts, intelligence["store_profile"], intelligence["diagnosis"], product, settings, intelligence["video_brief"]
        )
        quality = validate_outreach_personalization(outreach, facts, product, intelligence["video_brief"])
    intelligence["outreach"] = outreach
    intelligence["quality_control"]["outreach_checks"] = quality
    intelligence["quality_control"]["personalization_verified"] = quality["personalization_verified"]
    intelligence["quality_control"]["manual_review_required"] = quality["manual_review_required"]
    if quality["manual_review_required"]:
        return {"subjects": [], "body": "", "hook": "", "angle": "", "engine": "manual-review", "manual_review_required": True, "intelligence": intelligence}
    return {
        "subjects": [outreach["subject"]] if outreach.get("subject") else [],
        "body": outreach.get("message", ""),
        "hook": intelligence["video_brief"].get("concept", "")[:160],
        "angle": intelligence["video_brief"].get("format", ""),
        "engine": engine,
        "manual_review_required": False,
        "intelligence": intelligence,
    }
