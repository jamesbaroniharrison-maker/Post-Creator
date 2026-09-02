# Project: Personal LinkedIn Content Engine

A personal, semi-automated LinkedIn content system: daily AI/market research, a curated
topic bank, voice-matched drafting using a CPIO/THBM content framework, and a reviewed
publish step. Full architecture, schema, and reasoning live in `content-engine-spec.md`
in this repo — read it before starting any level below. This file is deliberately
short; it's the checklist, hard rules, and a condensed engineering-lessons log, not the
full reference.

## Hard rules — do not violate these while building

- Python throughout, except the optional Tier B publish engine (Postiz/trypost — Node.js, self-hosted, called as an external service over its own API, never merged into this codebase)
- No video processing anywhere — audio notes get transcribed to text, photos get captioned, that's the full extent of media handling
- Drafting calls default to self-hosted Ollama (spec §5 has the reasoning); switchable to Gemini via `DRAFT_LLM_PROVIDER=gemini` in `.env`, but only once you've confirmed that's actually covered by what you pay for — Ollama is the safe default (free, local, no surprise billing). Research and photo-captioning calls can use a free-tier API (Gemini/Tavily) regardless, since nothing sensitive passes through those two specifically
- The privacy/PII scrub call (for raw personal notes with no research backing) always stays on Ollama, regardless of `DRAFT_LLM_PROVIDER`
- Nothing ever publishes to LinkedIn without an explicit human approval click, at every build level, no exceptions
- Localhost only — no network/cloud hosting; this runs on your own machine

## Build order

Seven levels, each with a "done when" check in `content-engine-spec.md` §7: environment
setup → database schema → voice engine → drafting + research engine → daily research
cron + topic bank → multimodal capture → Reflex dashboard. Build and verify one level
before starting the next — schema mistakes are expensive to unwind once the bank has
real data in it.

## Current status

All 7 levels have working code, tested against real APIs/data, not just made to
compile. The package lives at `linkedin_content_engine/linkedin_content_engine/`,
mirroring the level structure: `voice_engine/`, `drafting_engine/`, `research_cron/`,
`capture/`, `email_engine/`, `dashboard/`, plus `models.py`/`scheduling.py`/
`usage_tracking.py` at the top level.

## Repurposing pivot (2 Sept 2026)

This project originally targeted a different person's professional content (health
insurance advice for a named employer). It has been fully repurposed into a personal
content engine — every reference to that original context has been removed from the
codebase, database, and docs (the original owner keeps their own separate copy
elsewhere, so nothing needed archiving here). What changed:

- **Rename**: `wpa_content_engine` → `linkedin_content_engine` throughout (folders,
  imports, `rxconfig.py`, the `.bat` launcher, Scheduled Task names — old WPA-named
  tasks are auto-unregistered by the updated `scripts/register_*.ps1` if you re-run
  them). Git `origin` repointed to a new personal repo.
- **Fresh database**: the old `.db` (37 real posts, an insurance-domain topic bank, an
  adversarial PII test case naming a real person) was deleted outright, not migrated.
  Fresh migrations applied to `linkedin_content_engine.db`; a new login account
  replaces the old one.
- **New schema**: `Post` gained `funnel_stage`, `hook_posture`, `length_bucket`,
  `structural_format`, `media_pairing`, `media_note` — the THBM rotation variables (see
  below). `TopicBank.category`/`post_type` moved from industry/company to `ai`/`market`
  (`ai_commentary`/`market_commentary`/`personal_reflection`).
- **Content angle**: research and drafting now target AI (primary — human-in-the-loop/
  augmentation-leaning, but not ignoring the displacement angle), personal/professional
  life, degree progress, and projects, kept professional. `research.py`'s
  `TRUSTED_DOMAINS` and `research_cron/queries.py`'s `DAILY_QUERIES` rewritten
  accordingly (tech/AI trade press, primary lab sources, UK policy bodies, business/
  market coverage — insurance/NHS-specific domains removed).
- **Drafting methodology rewrite** (`drafting_engine/`): implements a CPIO (Convey/
  Package/Information/Order) planning step and THBM (Topic/Hook/Body/Media) execution
  levers on top of the existing voice-profile system. New `rotation.py` picks each
  post's funnel stage (TOF/MOF/BOF, weekly-ratio-rotated) and execution variables (hook
  posture, length, structural format, media pairing) **deterministically in Python**,
  excluding whatever the last 3 posts used — never left to the model to "remember,"
  per the pattern below that already fixed two reliability bugs in this codebase. A
  fixed negative-constraints list (no em dash, no corporate jargon, no rhetorical
  questions, no reversal framing) is enforced both in-prompt and, for the em dash, by a
  deterministic regex on the way out — same belt-and-braces pattern as the existing
  money redaction. A new narrow 6-gate audit LLM call checks each draft
  (Convey/Hook/Payoff/Scannability/Anti-Fatigue/Speech-test) with one retry on failure.
  `DraftOutput` gained `convey_statement` and `media_note`.
- **Provider switch**: `DRAFT_LLM_PROVIDER=ollama|gemini` env var added to `draft.py` -
  defaults to Ollama; the privacy scrub call is hard-pinned to Ollama regardless.
- **Privacy/PII scrub reframed**, not removed: still runs on any raw personal note (no
  research findings behind it), generalising a real private third party's name,
  workplace/location detail, or exact figure — reworded from "a client's diagnosis" to
  general third-party privacy, since personal/work notes can still name real people.

**Tested for real end to end, not just made to compile**: seeded a placeholder voice
corpus and ran the voice engine to a real profile; ran the drafting engine twice
against live Ollama (`llama3`) — once with a `--skip-research` adversarial note naming
a real person, a town, a company, and an exact figure (all four were fully generalised
in the output, tags stayed clean, rotation fields populated and varied) and once as a
research-backed AI topic (confirmed Tavily now returns results from the new tech/AI
domain list). New migration applied and verified via direct sqlite3 query.

## Engineering lessons carried over from the original build

These held regardless of content domain and are worth knowing before touching the
matching module:

- **`rx.Model` is deprecated** (Reflex 0.9.2+, removal at 1.0) but still used in
  `models.py` because Reflex's `alembic_autogenerate`/`ModelRegistry` only
  auto-discovers `rx.Model` subclasses; migrating to plain SQLModel needs manual
  registry wiring, not worth it yet on 0.9.8.
- **Ollama silently caps context at 2048 tokens** regardless of the model's real max —
  `close_read.py`/`draft.py` set `num_ctx` explicitly (`OLLAMA_NUM_CTX`, default 8192).
- **`llama3.2` (3B) unreliably echoes structured-output schema placeholder text back
  verbatim** instead of generating real content for some fields. `llama3` (8B) doesn't
  have this problem — it's the default despite the larger download. The fix pattern
  that actually worked: an explicit worked example in the prompt, in a different domain
  so it can't just be copied — not just a stronger instruction.
- **A small local model does not reliably follow a rule bundled alongside several other
  instructions in the same call.** This has broken twice: the close-read JSON-echo bug,
  and a PII scrub that was only asked to *flag* sensitive content (never remove it) and
  silently leaked adversarial test PII into both the post body and the @mention tags.
  Both were fixed the same way — split the one rule into its own narrow call rather
  than adding it to an already-busy prompt. The CPIO/THBM audit-gate check
  (`_run_audit_call` in `draft.py`) and the privacy scrub's verify step
  (`_still_identifying`) both follow this pattern deliberately.
- **Privacy/PII scrubbing needs two independent layers, not one rewrite call**: a
  deterministic regex (catches exact figures unconditionally, can't fail) plus a
  second, independent LLM call that only checks a narrow yes/no question ("does this
  still identify someone?") rather than trusting the first rewrite call got it right.
  If the check still finds something, retry the rewrite once with that pointed out
  explicitly, then verify again — an unresolved case overwrites `compliance_note` with
  an unmissable failure message rather than reading as "no concerns."
- **Few-shot example selection**: pick posts closest to the corpus's *median* length,
  not the shortest — the shortest posts tend to be one-line reactions, not
  representative examples.
- **`reflex_local_auth.login_page` isn't at the top level** — it's
  `reflex_local_auth.pages.login_page`. `rx.Base` doesn't exist in Reflex 0.9.8 — use
  plain `pydantic.BaseModel` for typed nested state models.
- **`@rx.event(background=True)` isn't supported on `rx.upload`'s target handler** —
  the upload handler must be quick and non-background; hand off slow work (transcribe/
  caption) to a separate background event so the UI doesn't block.
- **Free-tier API quotas need real testing, not assumed limits**: Gemini's
  `google_search` grounding tool needs billing even on the "free" tier (confirmed via a
  live 429), which is why research uses Tavily instead. A specific Gemini model's free
  tier can be far lower than expected (one capped at 20 requests/day, confirmed live) —
  `GEMINI_MODEL` is configurable in `.env` for exactly this reason, and a usage-counter
  table (`usage_tracking.py`) stops Tavily calls before the real monthly cap, rather
  than finding out mid-month via a hard failure.
- **Windows Scheduled Tasks**: `Register-ScheduledTask`/`schtasks /Change` need genuine
  elevation — a non-elevated window can fail with Access Denied without an obvious
  error; verify with
  `([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)`.
  `Register-ScheduledTask`'s CIM errors don't respect `$ErrorActionPreference` on their
  own — pass `-ErrorAction Stop` explicitly or a real failure can print a false
  "Registered" success line. Prefer one `-Daily -At <time>` trigger per job over a
  shared hourly poll-and-check trigger — hourly firing across a whole day is a real
  nuisance even when it's working exactly as designed.
- **`load_dotenv()` must be called explicitly** in every module that reads
  `os.environ` directly (not just relying on `reflex run`'s own path) — otherwise
  `.env` loads inconsistently depending on import order.

## Architecture notes worth keeping in mind

- Dashboard is split into 7 focused pages under `dashboard/pages/` (Home, Review,
  Accepted, Rejected, Topic Bank, Past Weeks, Settings), sharing one `DashboardState`
  and a `page_shell()` wrapper (`dashboard/components.py`).
- `scheduling.py` auto-assigns approved posts to a `scheduled_week` (Monday date
  string), filling the current week to a cap before spilling into the next; runs on
  every accept and every dashboard load.
- Review flow is Accept / Redraft / Reject — a redraft is implemented as a rejection
  with `rejection_reason="redrafted"`, not a new status value.
- Rejected posts are pruned to the 5 most recent after every reject/redraft.
- Email reminders (`email_engine/`) are fully day+time configurable from the dashboard,
  degrade to a clean "skipped, not configured" when SMTP credentials are blank, and
  check whether a personal post already exists this week before nudging.
- Design system: dark mossy-green/bronze palette in `assets/design_tokens.css`,
  Fraunces headings / Inter body / IBM Plex Mono labels, forced dark theme.
- `drafting_engine/persona.py` holds a hand-authored voice/lexicon seed and
  `drafting_engine/context/about_me.md` (loaded via `draft.py`'s `_load_about_me()`)
  holds real biographical facts (career/education/projects) - both are permanent
  prompt inputs, separate from the corpus-derived `voice_profile`, and both are
  gitignored (personal data) with only their `README.md`/structure tracked. A sibling
  `documents/` folder at the repo root holds raw source files (CV, diplomas, LinkedIn
  export) for the assistant to read from directly - also gitignored.

## Switching drafting to Gemini (2 Sept 2026)

Tested live with `DRAFT_LLM_PROVIDER=gemini`. Real findings, not assumptions:

- **`gemini-pro-latest` resolves to `gemini-3.1-pro`, which has a hard 0 free-tier
  quota** (`limit: 0` on both input tokens and requests, confirmed via the actual 429
  error body) - it's billing-gated, the same pattern as the research grounding tool
  hitting a paywall back in level 4. Not usable without enabling billing.
- `gemini-flash-latest` is the strongest model confirmed free-tier accessible with this
  key - noticeably better structured/fluent output than `gemini-flash-lite-latest`
  (used for research scoring), at the cost of being slow: ~40s even for a trivial
  3-word prompt (looks like real internal reasoning overhead, not just network
  latency). The drafting call's timeout is 240s to accommodate this - 120s wasn't
  enough and caused a real `ReadTimeout` on the first live test.
- New `GEMINI_DRAFT_MODEL` env var lets drafting use a different (stronger) model than
  `GEMINI_MODEL` (which stays on the cheap lite model for research scoring) - falls
  back to `GEMINI_MODEL` then the lite default if unset.
- **A real fabrication bug was caught and fixed while testing this**: the audit-gate
  check (`_run_audit_call`) only ever received the drafted post text, never the
  original topic/note it was drafted from - so it had no way to actually verify
  whether something was invented. On `gemini-flash-latest` this let a fluent,
  plausible-sounding fabricated anecdote (a fake "last week I ran a scenario analysis,
  cost forty-five pence" scene, complete with specific invented numbers) sail straight
  through undetected - a more capable model produces more convincing fabrications, not
  fewer, so this bug mattered more here than it did on llama3's clumsier fabrications.
  Fixed by passing `topic` into the audit call so gate 6 can do a direct, explicit
  sentence-by-sentence comparison against the real input, not just judge the post in
  isolation. Confirmed live: the identical topic that fabricated before now produces
  grounded commentary/advice with no invented scene.
