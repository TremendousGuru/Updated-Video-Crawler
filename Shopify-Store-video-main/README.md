# Outreach Studio

Upload a list of Shopify stores → the app crawls each one → writes a message that could only
have been written for that store owner → you review it → one click opens your email client with
the subject and body already filled in.

Everything runs on your machine. Nothing is sent without you pressing send.

---

## Run it

```bash
cd shopify-outreach
python3 -m pip install -r requirements.txt
python3 -m app.main
```

Then open **http://localhost:8848**.

Or use the launcher, which creates a virtualenv for you:

```bash
./run.sh
```

## Deploy on Streamlit Community Cloud

The Streamlit version uses the same crawler, message composer and SQLite data layer as the
FastAPI interface. To run it locally, install `requirements.txt` and start:

```bash
streamlit run streamlit_app.py
```

To deploy, push this project to GitHub, create an app in
[Streamlit Community Cloud](https://share.streamlit.io/), select the repository and branch,
and set `streamlit_app.py` as the app's main file.

Before making the app public, add these values under **App settings → Secrets** in Streamlit
Community Cloud. Keep them out of GitHub:

```toml
APP_USERNAME = "your-login-name"
APP_PASSWORD = "a-private-password-at-least-16-characters"
OPENAI_API_KEY = "optional-openai-compatible-api-key"
```

`APP_USERNAME` and an `APP_PASSWORD` of at least 16 characters are required; without them,
the Streamlit app stays locked. `OPENAI_API_KEY` is optional: without it, the app writes
messages with its built-in templates. An API key entered in the settings panel is kept only
for that browser session; use Streamlit Secrets for a persistent deployment key. After setting
`OPENAI_API_KEY`, the Settings sidebar reports when it detects the secret; select **Test API key**
to verify that the configured endpoint and model can return a short plain-text response before
processing stores. This test does not require the model to generate an outreach email or JSON.

**Data and privacy:** Community Cloud's local filesystem is not durable storage. The app
uses a local SQLite database, so lead records and settings can be lost when the app restarts
or is redeployed. The workspace is shared by authenticated users of that app, so use a private
deployment and do not treat it as a multi-user CRM. For long-term or sensitive lead storage,
connect a managed database with access controls and backups before relying on the deployment.

This is suitable for a private, single-user pilot after setting secrets and verifying the live
crawl with a small batch. It is not production-ready for sensitive or long-lived CRM data until
persistent managed storage and the required backup and access-control policies are configured.

The original FastAPI interface remains available locally with `python -m app.main`. Its
production password settings are separate from the Streamlit app's login secrets.

## Hosting and password protection

Set these environment variables on your Python host:

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (required to enable production checks) |
| `APP_USERNAME` | Login name; defaults to `outreach` |
| `APP_PASSWORD` | A private password of at least 16 characters |
| `HOST` | `0.0.0.0` (the production default) |
| `OUTREACH_DB` | Path to the database on the host's persistent disk |

The app uses the browser's HTTP Basic login prompt. Use HTTPS on the host so credentials
are encrypted in transit. Production startup stops if `APP_PASSWORD` is missing or shorter
than 16 characters. Locally, the app binds to `127.0.0.1` by default.

---

## The workflow

### 1. Add your list
Drag in a **CSV, XLSX or TXT** file, or paste rows straight into the box. Column order doesn't
matter and headers are optional — it reads the values and works out which column is which.

| Accepted | Example |
|---|---|
| `email, domain, store_name` | `hq@deathwishcoffee.com, deathwishcoffee.com, Death Wish Coffee` |
| domain only | `browngirljane.com` |
| email only (domain inferred) | `hello@allbirds.com` |
| any order, any separator | `hello@ogg.com \| ogg.com \| OGG` |

If a row has no email, the crawler looks for one on the site (homepage, contact and policy pages)
and fills it in. Missing store names are replaced with the store's real name from its own site.

### 2. Crawl & compose
Press **Crawl & compose**. The app shows batch progress and each store's current stage (queued,
crawling, composing, ready or failed), plus error details for failed stores, so you can see whether
work is moving while a long list is processing. Completed crawl facts and drafts are saved as each
store finishes. Per store it reads:

- **Homepage** — tagline, categories, what they sell
- **`/pages/about`** — story, founder name, founding year, brand values (this is where the best hooks live)
- **Privacy policy, shipping, returns, contact** — proves a real visit and often surfaces details worth referencing
- **`/products.json` + `/meta.json`** when the site is Shopify — real product names, prices, currency, collections, city
- **Up to three relevant Shopify product pages, when the page limit permits** — prioritizes specific product use details rather than price. It checks fetched HTML for product images and video elements. A video not detected in that HTML is not treated as proof of a customer problem.
- **Linked social profiles** — handles are collected when visible, but recent social posts are not assumed to have been reviewed. Social-content opportunities require explicit audit evidence.

It then writes one message per store from those facts: a subject line plus three options, an opener
that references something specific and checkable, who you are, the video offer, and a CTA.

Processing is concurrent up to the **Stores at once** setting. Keep the app page open until the
batch finishes; the progress display updates as each store moves through crawling and composing.

### 3. Review and send
Review any row to edit its draft and inspect the collected store facts and sources.

On a phone, first select **Open draft in Gmail** to open the default mail app with the recipient,
subject and body filled in; set Gmail as the phone's default mail app if needed. Send the message
in Gmail, return to the website, and select **Sent & Next**. This records the lead as sent and loads
the next Ready draft in the same review area. The website cannot verify delivery through `mailto:`,
so only select **Sent & Next** after sending. Sent leads can be filtered separately and cannot be
sent again from the review screen.

---

## How the writing works

**With an API key** (Settings → API key): each store's fact sheet goes to an LLM with strict rules —
never invent facts, never claim to have bought the product, no markdown, no "I hope this email finds
you well". It returns a subject set plus the body as JSON.

Works with any OpenAI-compatible endpoint — change **Base URL** + **Model** for OpenRouter, Groq,
Together, or a Gemini compatibility endpoint. Use **Test** to confirm before a big run.

**Without a key**: deterministic local templates use the same crawled facts, diagnosis, and evidence
checks. The app marks these drafts as locally composed. If an AI request fails (for example, due to
a bad key, rate limit, or network error), it falls back to the same local path and records the reason
in the composition note.

Product candidates are scored from 0–10 using the evidence-backed opportunity, suitability of video,
visual potential, brand fit, and any explicitly audited opportunity to improve existing video.
Scores of 8–10 can be drafted normally. Scores of 5–7 produce a draft with a review recommendation,
but review confirmation is optional and does not gate sending. Candidates below 5 are not drafted.
A creative opportunity is not presented as proof of low sales, conversion problems, or customer
confusion. If the available evidence does not support a specific message, the app abstains and
requests manual review.

---

## Settings that matter most

| Setting | Why |
|---|---|
| **Your name / company** | Used in the sign-off. Without it your emails end without a sender. |
| **What you do** | The service description is connected to the selected product opportunity rather than used as a generic opener. |
| **Video offer line** | Defaults to offering a storyboard for review; it does not claim a video has already been made. |
| **Call to action** | Defaults to a low-pressure invitation to see a short storyboard. |
| **First subject idea** | Defaults to `a short video idea for {product}`; `{product}` is replaced with the selected product title. |
| **Tone** | Defaults to warm, concise, specific, conversational wording without pressure or sales promises. |
| **Opt-out line** | Keeps you on the right side of spam law and improves replies. Leave it on. |
| **Stores at once** | Defaults to 3 to keep crawl concurrency modest. |
| **Delay between requests** | Defaults to 0.75s. Raise it if a store starts refusing connections. |
| **Maximum pages per store** | Defaults to 10 to leave room for relevant product-page audits after core store pages. |
| **Respect robots.txt** | On by default. Leave it on. |

---

## Deliverability, honestly

This is the part that decides whether the tool works, not the code.

- **Volume kills.** Gmail allows ~500 recipients/day and far less for a new account. 20–40/day from a
  normal address beats 300 from a fresh one that gets throttled or flagged.
- **Warm up.** Send a handful a day for the first week, reply to your own test sends, then scale.
- **Plain text wins.** These messages have no images, no tracking pixels, no HTML — that's deliberate.
- **Personalization is your best filter-avoider.** A message that names the actual product is not the
  pattern spam filters are trained on.
- **Reply or stop.** If someone replies "no", stop. The app tracks `sent` rows so you don't hit them twice.
- **Rules vary.** Cold B2B email is legal in the US under CAN-SPAM (with a real identity and opt-out).
  In the EU/UK, GDPR/PECR generally require a legitimate-interest basis and a clear opt-out — plus the
  subject should be relevant to their business role. In Canada, CASL wants consent or a real
  existing-relationship basis. Use the opt-out line and keep volumes sane.

---

## When a store fails

Rows are marked `failed` with the reason, and a **Re-crawl site** button appears in the drawer.

| Message | What it means |
|---|---|
| `homepage unreachable (HTTP 403)` | Store is blocking bots. Retry later or raise the delay. |
| `robots.txt disallows crawling` | Their robots.txt forbids it. Respect it — that's why it's checked. |
| `no products found` | Not Shopify, or a password-protected/coming-soon store. |
| `no real about page prose found` | The about URL exists but is only navigation. The message uses homepage facts instead. |
| Row shows `no email yet` | Nothing findable on the site — add it to your sheet manually. |
| `AI failed, used template` | The toast names the API error (bad key, quota, model name). Templates filled in meanwhile. |

Flags on each row tell you what's soft: `not detected as Shopify`, `site may be password-protected`,
`generic mailbox (gmail/yahoo) - not a brand domain` (that last one is a real deliverability signal).

---

## Export

- **Export CSV** — `email, store_name, domain, subject, body, status, engine, hook, sent_at`
- **Export JSON** — the same plus the full fact sheet per store, for use in your own tooling

Useful if you'd rather load the finished messages into a sending platform instead of clicking through
your mail client.

---

## Files

```
shopify-outreach/
├── run.sh                 one-command launcher (creates .venv, installs, runs)
├── requirements.txt
├── outreach.db            your data (SQLite) - delete to start over
└── app/
    ├── main.py            FastAPI routes + export endpoints
    ├── ingest.py          CSV/XLSX/TXT parsing, column detection
    ├── crawler.py         Shopify JSON + HTML crawling, fact extraction
    ├── compose.py         LLM prompt + template writer
    ├── pipeline.py        batch queue, concurrency, live event stream
    ├── db.py              SQLite schema and queries
    └── static/            the interface
```

Re-crawling a lead refreshes its facts and rewrites the message. **Rewrite this one** keeps the facts
and writes a fresh message from them — that's how you get variety when two stores in a batch are similar.
