# PayloadOne — Shipping Plan
### #BuildQuikChallenge Season 1

---

## 1. Idea Validation

**The problem in one sentence:**
Backend developers integrating Paystack and Flutterwave webhooks repeatedly write the same insecure, fragile boilerplate — and most get at least one of three things wrong: signature verification, duplicate processing, or payload normalisation.

**How I discovered this:**
After going through webhook integration documentation for both Paystack and Flutterwave, I noticed that:
- The official docs show signature verification as an afterthought, not a requirement
- AI coding tools (Copilot, ChatGPT) frequently generate webhook handlers with no signature check at all
- Developers in Nigerian developer communities (Devcenter Discord, Twitter/X threads) regularly report double-credited wallets and duplicate order fulfilments after launches

**Who has this problem:**
Backend developers at early-stage Nigerian and African startups building payment-enabled products — wallet apps, e-commerce backends, SaaS platforms charging in NGN. They are not security experts. They are moving fast, and webhook correctness is an invisible problem until something goes wrong in production.

**Ideal user:**
A backend developer at a Lagos-based fintech or SaaS startup, 2-5 years of experience, using FastAPI or Flask, who has integrated Paystack before but isn't confident their webhook handler is production-safe.

**How they solve it today:**
They copy-paste code from the Paystack or Flutterwave documentation, maybe a Stack Overflow answer, and wire it into their app manually. Each developer reinvents the same solution. There is no standard library that handles all three problems (signature, normalisation, idempotency) together.

**Validation:**
- Searched Twitter/X for "paystack webhook double charge", "flutterwave webhook duplicate" — found multiple developer complaints
- Reviewed 5+ open source Nigerian SaaS repos on GitHub — none had atomic idempotency on their webhook handlers
- Reviewed both Paystack and Flutterwave official docs — neither enforces signature verification in their code samples

---

## 2. Target Audience

**Primary user:**
A backend developer in Nigeria or wider Africa building a product that accepts payments via Paystack or Flutterwave. They know Python. They have integrated at least one payment gateway before. They are not thinking about webhook security until something breaks in production.

**Where they hang out:**
- Twitter/X — Nigerian tech Twitter is very active (`#buildinpublic`, `#NaijaDevs`)
- Devcenter Square Discord
- GitHub — searching for Paystack or Flutterwave Python libraries
- Reddit — r/Python, r/webdev
- WhatsApp developer groups

**What would make them switch:**
A `pip install payloadone` that replaces 80 lines of fragile boilerplate with 10 lines of clean, safe code — and works with the framework they are already using.

---

## 3. Tech Stack Rationale

- **Python** — The dominant language for backend development among the target audience. FastAPI and Flask are the most commonly used frameworks in the Nigerian startup ecosystem for APIs.

- **Pydantic v2** — Used for the `UnifiedEvent` model because it enforces types at runtime, validates email addresses, and makes the normalised output reliable and self-documenting. No manual validation code needed.

- **Redis (primary idempotency backend)** — Atomic `SET NX EX` is a single command that checks and reserves a key simultaneously. No race condition possible. Expires automatically after TTL.

- **PostgreSQL (fallback)** — `INSERT ... ON CONFLICT DO NOTHING RETURNING` is the SQL equivalent atomic primitive. Offered as a fallback for teams that already have Postgres and do not want to add Redis.

- **Python stdlib `hmac` + `hashlib` only** — No third-party cryptography dependencies. Reduces supply chain attack surface. Both primitives are battle-tested and available in every Python environment.

- **Framework-agnostic core** — The pipeline has zero knowledge of HTTP frameworks. Thin adapters for FastAPI, Flask, and Django sit on top. This was a deliberate tradeoff — more code to write upfront, but the library works everywhere without pulling in framework dependencies.

- **Tradeoffs made:**
  - Chose Poetry over plain pip for dependency management — adds a setup step but gives reproducible installs and clean extras (`payloadone[redis,fastapi]`)
  - Chose async-first design — means Flask users need a sync wrapper, but async is the right default for I/O-heavy webhook processing

---

## 4. MVP Scope

**The one core feature:**
Drop-in webhook middleware that verifies, deduplicates, and normalises Paystack and Flutterwave webhook payloads into a single `UnifiedEvent` model — in a 7-stage pipeline — before calling your handler.

**What was built:**

| Feature | Status | Priority |
|---|---|---|
| Paystack HMAC-SHA512 signature verification | ✅ Done | Must have |
| Flutterwave secret hash verification | ✅ Done | Must have |
| Redis idempotency backend | ✅ Done | Must have |
| PostgreSQL idempotency backend | ✅ Done | Must have |
| `UnifiedEvent` normalised model | ✅ Done | Must have |
| FastAPI adapter | ✅ Done | Must have |
| Flask adapter | ✅ Done | Must have |
| `@manager.on()` decorator API | ✅ Done | Must have |
| 91.9% test coverage | ✅ Done | Must have |
| Live demo API (QuikDB) | ✅ Done | Must have |
| Hosted documentation site | ✅ Done | Must have |
| Django adapter | ⏭ Skipped | v2 |
| Stripe adapter | ⏭ Skipped | v2 |
| OpenTelemetry tracing | ⏭ Skipped | v2 |
| Prometheus metrics | ⏭ Skipped | v2 |
| CLI signature verification tool | ⏭ Skipped | v2 |
| Dead-letter queue hook | ⏭ Skipped | v2 |

**What v2 looks like:**
- Django adapter (large Django userbase in the target market)
- Stripe adapter (international expansion)
- `on_handler_error` dead-letter hook so failed events don't silently disappear
- OpenTelemetry spans per pipeline stage for distributed tracing
- A CLI tool: `payloadone verify --provider paystack --secret sk_... --payload payload.json`

---

## 5. Testing

**Automated test suite:**
- **82 tests passing, 7 skipped** (asyncpg optional dependency not installed in CI)
- **91.9% code coverage** — enforced via `pytest-cov --cov-fail-under=90`
- Tests run on Python 3.11 and 3.12 via GitHub Actions CI on every push

**What is tested:**

| Category | Tests |
|---|---|
| Paystack signature — valid, invalid, missing, tampered, case-insensitive | ✅ |
| Flutterwave signature — valid, invalid, missing, case-insensitive | ✅ |
| Paystack normalisation — all event types, amount in kobo, raw payload preserved | ✅ |
| Flutterwave normalisation — float → kobo conversion, all event types | ✅ |
| Idempotency — first occurrence, duplicate, cross-provider isolation, TTL | ✅ |
| Full pipeline — happy path, duplicate, bad signature, unknown provider | ✅ |
| FastAPI adapter — 200 on success, 401 on bad signature | ✅ |
| Flask adapter — 200, 401, 400, 422 response codes | ✅ |
| Configuration validation — all missing/invalid config combinations | ✅ |

**Edge cases covered:**
- Tampered payload (valid signature on wrong body)
- `\r` carriage returns in secret keys (Windows line ending issue)
- Floating-point amount conversion (`99.99 NGN → 9999 kobo` using `round()`)
- `verify_signature` returning `False` instead of raising on any exception
- Concurrent duplicate delivery (atomic Redis `SET NX`)

**Manual testing:**
- Live demo deployed and tested end-to-end with real curl requests
- Valid Paystack webhook → `200 acknowledged`, event appears in `/events`
- Valid Flutterwave webhook → `200 acknowledged`
- Bad signature → `401` returned, handler never called
- Duplicate webhook → `200` returned, handler called exactly once
- Unknown provider → `400` returned

---

## 6. Deployment and Monitoring

**Health endpoint:**

```
GET https://payloadone-demo.quikdb.net/health
→ {"status": "ok"}
```

**Infrastructure:**
- **Demo backend** — QuikDB Compute (Python, uvicorn)
- **Idempotency store** — Upstash Redis (TLS, free tier, persistent)
- **Documentation** — QuikDB Compute (Python static file server)
- **CI/CD** — GitHub Actions (lint → type check → test → optional PyPI publish on tag)

**Reliability measures:**
- All secrets stored in QuikDB encrypted environment variables — nothing hardcoded
- `MisconfigurationError` raised at startup if any required env var is missing — fails loudly before accepting traffic
- Every pipeline exception has a specific HTTP status code mapping — no unhandled 500s on expected error paths
- QuikDB auto-restarts containers on crash
- `/health` endpoint for QuikDB health checks

**What happens if it crashes:**
QuikDB restarts the container automatically. Because Redis holds the idempotency state externally, no in-flight state is lost on restart. The gateway will retry unacknowledged webhooks and they will be processed correctly on the next attempt.

---

## 7. Launch Plan

**Getting the first 10 users:**

1. **Post on Twitter/X with #BuildQuik** — share the demo URL, a 2-minute screen recording of a webhook being processed end-to-end, and tag @PaystackHQ and @theflutterwave
2. **Post in Devcenter Square Discord** — Nigerian developer community, direct audience match
3. **Write a short Twitter/X thread** — "I built PayloadOne because I kept seeing the same webhook mistakes in Nigerian fintech repos — here's the 3 problems it solves and how to use it in 10 lines of code"
4. **Submit to GitHub trending** — open source Python library, tag it `paystack`, `flutterwave`, `webhooks`, `python`
5. **Post on Reddit** — r/Python and r/webdev with a technical write-up of the idempotency design
6. **Reach out directly** — find 5 Nigerian SaaS repos on GitHub with insecure webhook handlers, open a GitHub issue linking to PayloadOne as a solution
7. **Publish to PyPI** — `pip install payloadone` is the fastest path from discovery to usage

**After the challenge:**
- Maintain the library and respond to GitHub issues
- Add Django adapter (most requested feature based on community polling)
- Write a blog post: "How we prevented double-funded wallets at scale using atomic Redis idempotency"
- Submit to Awesome Python and Awesome FastAPI lists