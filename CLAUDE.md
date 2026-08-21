# Project: WPA LinkedIn Content Engine

Semi-automated LinkedIn content system for a WPA-affiliated UK private medical insurance adviser. Full architecture, schema, and reasoning live in `content-engine-spec.md` in this repo â read it before starting any level below. This file is deliberately short; it's the checklist and hard rules, not the reference.

## Hard rules â do not violate these while building

- Python throughout, except the optional Tier B publish engine (Postiz/trypost â Node.js, self-hosted, called as an external service over its own API, never merged into this codebase)
- Nothing installs on her work computer, ever â any dashboard is browser-only
- No video processing anywhere â audio notes get transcribed to text, photos get captioned, that's the full extent of media handling
- Drafting calls default to self-hosted Ollama (spec Â§5 has the reasoning); research and photo-captioning calls can use a free-tier API (Gemini/Groq) since nothing sensitive of hers passes through those two specifically
- Nothing ever publishes to LinkedIn without an explicit human approval click, at every build level, no exceptions

## Build order

Seven levels, defined with a "done when" check for each in `content-engine-spec.md` Â§7. Build and verify one level before starting the next, even where skipping ahead looks safe â level 5 depends on level 2's schema being right, and schema mistakes are expensive to unwind once the bank has real data in it.

1. Environment & project setup
2. Database schema
3. Voice engine
4. Drafting + research engine
5. Daily research cron + topic bank
6. Multimodal capture
7. Reflex dashboard

## Current status

Level 1: complete. `wpa_content_engine/` holds a Reflex 0.9.8 app (hello-world page) on Python 3.14, venv at `venv/`, `requirements.txt` and `.env.example` in place, SQLite db provisioned via `reflex db init` + `reflex db migrate` (Alembic scaffolding under `wpa_content_engine/alembic/`), confirmed booting locally with `reflex run` (frontend + backend both returned HTTP 200).

Level 2: complete. Schema defined in `wpa_content_engine/wpa_content_engine/models.py` (`TopicBank`, `Post`, `VoiceSample`, `VoiceProfile`, `JobRun`, matching spec Â§9) using `rx.Model` â noted as deprecated as of Reflex 0.9.2 (slated for removal at 1.0) but kept because Reflex's own `alembic_autogenerate`/`ModelRegistry` only auto-discovers `rx.Model` subclasses; migrating to plain SQLModel would need manual registry wiring, not worth it yet on 0.9.8. Migration `5ec17dddc924_level_2_schema.py` generated and applied; confirmed via direct sqlite3 query that all 5 tables exist with correct columns, FK (`post.source_bank_id` â `topicbank.id`), and are queryable (0 rows each, as expected).

Level 3: complete. Pipeline lives in `wpa_content_engine/wpa_content_engine/voice_engine/`:
`ingestion.py` (writes to `voice_samples`), `keyness.py` (word-frequency deltas vs.
`wordfreq`'s general-English baseline), `structural.py` (sentence length, punctuation,
CTA/question-opening rates, etc.), `close_read.py` (qualitative LLM read â self-hosted
Ollama only, per hard rules, since her raw writing is sensitive), `build_profile.py`
(merges all three + curated few-shot examples into the single `voice_profile` row),
`run.py` (CLI entrypoint: `python -m wpa_content_engine.voice_engine.run`).

37 of her real LinkedIn posts (comments excluded â different register from authored
posts, would've skewed structural stats) loaded into `voice_samples` and the pipeline
run end to end. Two real bugs found and fixed during this run:
- `llama3.2` (3B) unreliably echoed the JSON schema's placeholder text back verbatim
  instead of generating real analysis for 3 of 4 close-read fields. Rewrote the prompt
  with an explicit worked example (different domain, so it can't be copied) and switched
  the default model to `llama3` (8B), which did not have this problem. `OLLAMA_MODEL` in
  `.env` controls this.
- Ollama silently caps context at 2048 tokens regardless of the model's real max, which
  would've truncated a 37-post corpus. `close_read.py` now sets `num_ctx` explicitly
  (default 8192, `OLLAMA_NUM_CTX` env override).
- Few-shot example selection originally picked the *shortest* posts, which surfaced
  one-line reactions ("Very proud of this girl!") instead of representative full posts.
  Now picks posts closest to the corpus's median length.

Final run against her real corpus produced grounded, varied output across keyness (WPA,
Chartwell, Papyrus, CRX, EAP all correctly surfaced as distinctive vocabulary),
structural stats (avg 64 words/post, minimal hashtag/emoji use, low exclamation rate â
matches the real corpus), and the close read (self-deprecating, matter-of-fact,
encouraging; notes her habit of opening with "So" to pivot problem→solution).

Level 4: complete. Pipeline lives in `wpa_content_engine/wpa_content_engine/drafting_engine/`:
`schema.py` (`DraftOutput` pydantic model: text, hashtags, tags, suggested_day, sources,
compliance_note), `research.py` (Tavily search restricted to spec Â§3a's trusted-domain
allow list), `draft.py` (Ollama-only drafting call combining voice profile + research +
compliance instructions), `pipeline.py` (orchestrates both + saves to `posts`), `run.py`
(CLI: `python -m wpa_content_engine.drafting_engine.run --topic "..." --post-type ...`,
`--skip-research` for posts like personal reflections that don't need external facts).

**Schema change**: `posts` (built in level 2) only had `draft_text` - no columns for
hashtags/tags/suggested_day/sources/compliance_note, even though the dashboard (spec
Â§3d) needs all of these as separate editable elements. Added via a new migration while
the table was still empty (`models.py`, migration
`8124847f1d14_level_4_add_hashtags_tags_suggested_day_.py`).

**API decisions**: Gemini's `google_search` grounding tool 429'd on the very first call
even on the free tier (needs billing enabled) - confirmed live, not assumed. Switched to
Tavily (search API built for LLM use, genuinely free, 1000 searches/month, no billing
required) for the research call instead. `TAVILY_API_KEY` in `.env`. Gemini key kept
configured for level 6 photo-captioning, where it should still work fine (no search tool
needed there).

**Real bug found and fixed**: `python-dotenv` was installed since level 1 but
`load_dotenv()` was never actually called anywhere, so `.env` was silently never loaded
outside of `reflex run` (which reads it via a different path). `research.py`, `draft.py`,
and `close_read.py` all read `os.environ` directly and could silently get nothing
depending on import order. Fixed by calling `dotenv.load_dotenv()` in `rxconfig.py` and,
defensively, in each of those three modules directly (so they don't depend on import
order to work standalone).

Tested end to end against real data: (1) a WPA/Which? Recommended Provider industry
insight, research-grounded - correctly cited `wpa.org.uk` as its source; (2) a personal
reflection with `--skip-research` - no fabricated sources, stayed in commentary. Both
saved correctly to `posts` with all new columns populated.

Level 5: code complete and tested end to end; scheduled task not yet registered (she
hasn't asked for it live yet). Pipeline lives in
`wpa_content_engine/wpa_content_engine/research_cron/`: `queries.py` (standing daily
search queries tagged industry/company per spec Â§1's two research-backed post types),
`discovery.py` (Tavily news-mode search, reuses level 4's trusted-domain allow list),
`dedup.py` (lexical similarity against recent bank entries, spec Â§4 LLM08: no
embeddings needed at this scale), `scorer.py` (Gemini classifies each finding into
high/mid/discard + category + summary - plain generation, no search tool, so it's not
hit by the level 4 billing-gated grounding issue), `pipeline.py` (orchestrates all of
it, idempotent per day via `job_runs` so the daily-trigger + at-logon-catchup pair from
spec Â§5 is safe to both fire), `run.py` (CLI entrypoint, `--force` bypasses the
once-per-day guard).

Tested for real against live Tavily/Gemini: first run stored 1 mid-tier + 15 discard,
0 high. Initially looked like a scorer bug (a WPA "Which? Recommended Provider" result
and a new-policy-launch result both scored discard, despite looking postworthy) - but
checking the raw Tavily results showed those pages were dated 2020-2025; Tavily's
"news" mode surfaces by recrawl date, not publish date, so old evergreen WPA pages
resurface under a "last 1 day" filter. Discard was the correct call - the scorer is
properly distinguishing genuinely current news from old pages being re-crawled, exactly
per spec Â§3a's "specific, current" bar for high tier. Zero high-tier on a given day is
expected behaviour, not a failure - it's exactly why spec Â§1's flex-down cadence rules
exist. Second (forced) run correctly caught 15/16 as duplicates by URL.

`scripts/register_scheduled_task.ps1` registers the Windows Scheduled Task (daily +
at-logon dual trigger per spec Â§5) - written and ready, but not yet run. To go live:
run it from an elevated PowerShell prompt in `wpa_content_engine/scripts/`.

Level 6: complete. Pipeline lives in `wpa_content_engine/wpa_content_engine/capture/`:
`transcribe.py` (self-hosted `faster-whisper`, CPU, `base` model - not the reference
openai-whisper package, since faster-whisper decodes via bundled PyAV wheels and needs
no system ffmpeg install), `caption.py` (Gemini vision via the Interactions API's
multimodal image input - free-tier, per CLAUDE.md hard rules, since photo content isn't
in the same sensitivity class as her voice/notes text), `ingest.py` (dispatches by file
extension: text passes through, audio â†’ transcript, photo â†’ caption + copied into
`assets/uploads/` under a UUID name for later attachment; **video is explicitly
rejected** with a clear error, per the hard rule - not silently processed or dropped),
`run.py` (CLI entrypoint).

Tested for real, not just plumbing: generated an actual spoken WAV via Windows' offline
SAPI TTS ("This is a test voice note about private medical insurance...") and confirmed
`faster-whisper` transcribed it almost exactly (only divergence: "well-being" vs.
"wellbeing", a trivial hyphenation difference). Photo captioning tested against two
synthetic PNGs (pure-Python-generated, no Pillow needed) - Gemini's descriptions
accurately matched their actual colours/layout with no hallucinated content. Video
rejection confirmed to raise loudly rather than fail silently. Then closed the full
loop: fed real transcribed audio notes into the level 4 drafting engine
(`generate_and_save_draft(..., skip_research=True)`) and got a coherent company-update
draft in her voice - proving capture â†’ drafting actually connects end to end, not just
each piece in isolation.

One environment quirk worth knowing: Hugging Face's model download (first-run only, to
fetch Whisper's weights) failed to resolve DNS from the Bash/Git-Bash shell specifically
(`huggingface.co` unreachable) while Tavily/Gemini calls worked fine from the same
shell, and PowerShell could reach `huggingface.co` without issue. Worked around by
running that one command through PowerShell instead. Once cached locally
(`~/.cache/huggingface`), subsequent runs work fine from Bash too, since no network call
is needed at that point.

Level 7: code complete, compiled and serving successfully; **not yet visually verified
in a browser** (no browser-automation tool available in this environment - see caveat
below). Login account created directly (username `ben`; password shared with the user
out of band, not stored anywhere in this repo).

Pages/state live in `wpa_content_engine/wpa_content_engine/dashboard/`: `state.py`
(`DashboardState` - loads posts/bank/stats from DB, all edit/approve/reject/publish/
likes/comments/topic-bank/upload event handlers), `components.py` (stat cards, editable
hashtag/tag chip lists, post cards, topic bank cards, upload box), `page.py` (assembles
the page, wrapped in `reflex_local_auth.require_login`).

**Auth**: uses `reflex-local-auth` (the official Reflex-team package - this *is* the
"built-in auth" spec Â§3d meant; it's not literally inside the `reflex` core package,
but it's the blessed first-party solution, not something hand-rolled). Its `LocalUser`/
`LocalAuthSession` tables were migrated alongside the app's own tables. No public
`/register` route was wired up by design - single-user system (spec Â§9), so her one
account was created directly via a script rather than exposing self-service signup.
The `AUTH_SECRET_KEY` env var scaffolded back in level 1 turned out to be dead - this
package signs sessions with Reflex's own internal app secret, not a configurable env
var - so it's been removed from `.env`/`.env.example`.

**Real bugs hit and fixed while wiring this up**:
- `rx.Base` doesn't exist in Reflex 0.9.8 (removed/renamed) - typed nested state models
  (`PostView`, `BankView`) use plain `pydantic.BaseModel` instead.
- `reflex_local_auth.login_page` isn't at the top level - it's
  `reflex_local_auth.pages.login_page`.
- `@rx.event(background=True)` isn't supported on `rx.upload`'s target handler - the
  upload handler has to be a quick, non-background function that saves the file(s) and
  hands off to a separate background event (`process_uploaded_files`) for the actual
  slow ingest+draft work, so the UI doesn't block during audio transcription/captioning.

**Verification done**: the app compiles and both `/` and `/login` serve HTTP 200.
Since no browser-automation tool is available in this environment, the actual
click-through (login form, approve/reject buttons, chip add/remove, upload widget) has
**not** been visually exercised - only the underlying logic has, by calling the exact
same DB/pipeline code the event handlers call, directly: generated a real draft from an
unused topic bank row (citing its source correctly, bank row correctly marked
`used=True`), simulated approve/reject/publish/likes/comments and confirmed `posts`
updated correctly, and recomputed the stats panel's exact logic against real data
(3 decided posts, 67% acceptance rate, correct avg review/publish times). One post was
deliberately left in `drafted` status and one topic bank row deliberately left unused,
so there's something live to click through when checked in an actual browser.
**This still needs a real look in a browser before being called fully done** - run
`reflex run` from `wpa_content_engine/` and log in at `/login`.

**Post-level-7 additions (requested after the initial build)**:

- **Design system**: restyled to match `portfolio-site`'s dark mossy-green/bronze
  editorial palette (colors and fonts copied verbatim from that project's
  `styles.css` lines 5-17 - see `assets/design_tokens.css`). Fraunces for headings,
  Inter for body text, IBM Plex Mono for labels/stat values, loaded via Google Fonts.
  The token CSS variables are mapped onto Radix Themes' own `--gray-*`/`--accent-*`
  variables (`.radix-themes` override block) so every `rx.card`/`rx.button`/etc. picks
  up the palette automatically rather than needing per-component color overrides.
  Theme is forced dark (`appearance="dark"`) - the light/dark toggle was removed
  since this is a deliberate single palette, not a themeable app. Theme config lives
  in `rxconfig.py` via `rx.plugins.RadixThemesPlugin(theme=...)`, not `rx.App(theme=...)`
  (the latter is deprecated as of Reflex 0.9.0).
- **Quick actions panel** (`components.quick_actions_section`, spec extension, not in
  the original document): three cards -
  1. **Generate a post now** - topic + post type in, runs the full research+draft
     pipeline on demand (doesn't wait for the topic bank).
  2. **Run research now** - triggers `research_cron.pipeline.run_daily_research(force=True)`
     directly from the dashboard instead of waiting for the scheduled task.
  3. **Force next search topics** - a small queue (new `ForcedTopic` table: topic,
     category, consumed bool) that gets folded into `DAILY_QUERIES` on the *next*
     research run (scheduled or manual) and marked consumed afterward - a one-shot
     nudge, not a permanent addition to the standing query list.

  Tested for real: queued a forced topic, ran the exact discover -> score -> consume
  code path the pipeline uses (isolated from the 5 standing queries, to conserve
  Tavily/Gemini quota) - found a real WPA product page, scored it, banked it, and
  confirmed the forced topic was removed from the pending queue afterward.
- **Depth/contrast refinement** (second design pass, HUD feedback after first look):
  darker base (`#090D0B`), lifted card surface (`#121815`), distinct input-field
  surface (`#1B2420`), and low-opacity glowing card borders
  (`rgba(82, 183, 136, 0.15)`) instead of a hard border line. Body/data text moved
  from near-white to an off-white/cream (`#E2E8F0`) to cut glare. Serif is now
  strictly reserved for real page/section headings (`rx.heading` only, everything
  else - buttons, labels, inputs, badges - stays on Inter). Primary CTAs (Approve,
  Research + draft, Draft from note, Upload & draft, Generate draft, Mark published)
  switched from saturated green to the warm bronze/gold accent; secondary actions
  (Add, Queue topic, Copy text, Run research now) switched to outlined/ghost style
  to cut visual noise. Status is now rendered as soft pill badges with per-status
  muted background + soft text color (`.hud-pill-*` classes) instead of solid Radix
  badges. Stat numbers enlarged to 32px bold with a small muted uppercase label.
  Card/input padding doubled (`--pad: 1.25rem`); textareas got `resize="vertical"`
  so they grow instead of clipping.
- **Non-technical-usability audit** (requested directly): the standing goal is that
  someone with zero coding experience, whose only intended action is "open the app,"
  hits no dead ends. Confirmed with the user first that she'll be sitting at this same
  computer (not a separate device) - so this stays localhost-only; real network/cloud
  hosting (spec Â§5's original plan) is explicitly not built and would need its own
  security pass (HTTPS, hardening beyond localhost auth) if that changes later.
  - **`Start WPA Content Engine.bat`** (project root): double-click launcher. Clears
    any stale processes still holding ports 3000/8000 from a previous run, checks
    Ollama is reachable and starts it if not, launches the server in its own window,
    polls until the frontend responds, then opens the browser straight to `/login`
    automatically. Tested for real (not just written and assumed): ran a
    non-interactive copy of the script end to end and confirmed it actually gets the
    dashboard serving HTTP 200 with no manual steps.
  - **`HOW TO USE.txt`** (project root, plain English, no jargon): step by step -
    starting the app, logging in, what each dashboard section does, and what to do if
    something looks broken. Deliberately separate from `CLAUDE.md`, which stays the
    developer-facing build log she'll never need to open.
  - **Robustness pass**: `load_dashboard` (runs automatically on every page load)
    wasn't wrapped in error handling - a DB hiccup there would have blanked the whole
    page with no way for a non-technical user to recover. Now it fails into a visible,
    plain-English status message instead. That status message also moved from being
    buried inside the upload box to a dismissible banner at the top of the page, so
    upload/generate/research failures are impossible to miss. Every backend call that
    can fail (Ollama down, API quota, bad file) already routed through existing
    try/except blocks into `status_message` - confirmed by re-reading every background
    event handler in `dashboard/state.py`, not just the new ones.
  - **Known remaining limitation, not fixed**: there's no self-service password reset
    (no email system, single-user app) - if she forgets her password, only a direct DB
    script fix works. Documented in `HOW TO USE.txt` as "contact James," which is an
    acceptable tradeoff at this scale but worth knowing about.
- **Trusted source expansion** (requested directly): `drafting_engine/research.py`'s
  `TRUSTED_DOMAINS` grew from 9 to 33 domains, organized by category - NHS/gov/policy
  think tanks (added `ons.gov.uk`, `parliament.uk`, `nice.org.uk`, `nhsconfed.org`,
  `kingsfund.org.uk`, `nuffieldtrust.org.uk`, `health.org.uk`, `laingbuisson.com`),
  insurance trade press (added `biba.org.uk`, `insuranceage.co.uk`,
  `insurancebusinessmag.com`, `insurancetimes.co.uk`, `postonline.co.uk`,
  `protectionreview.co.uk`, `theactuary.com`), adviser press (`ftadviser.com`,
  `professionaladviser.com`, `corporate-adviser.com`), employee benefits/EAP sources
  (`employeebenefits.co.uk`, `reba.global`, `cipd.org` - spec Â§1's EAP content angle),
  and mainstream UK news (`which.co.uk`, `bbc.co.uk`, `theguardian.com`). Deliberately
  still excludes competitor insurer newsrooms and generic SEO/comparison sites, per the
  original mandate. `research_cron/queries.py`'s `DAILY_QUERIES` expanded from 5 to 14
  so these new domains actually get searched, not just sit unused in the allow list -
  added queries for NHS waiting times, employee benefits/wellbeing, protection
  insurance, broker/adviser news, workplace mental health, and market reports. Tested
  live: a query for "UK employee benefits workplace wellbeing news" correctly surfaced
  real `employeebenefits.co.uk` results that wouldn't have matched the old domain list.

**Real bug found during quota verification**: `gemini-3.7-flash`'s free tier caps at
**20 requests/day** - confirmed via a live 429 after exactly ~20 calls
(`generate_content_free_tier_requests` limit). This is nowhere near enough for daily
scoring at 14-query volume (30-70 scoring calls/day) - every call past the 20th was
silently falling back to `tier="discard"` via the existing broad exception handling,
meaning some of that day's earlier real research runs likely mis-scored genuinely good
findings as discard, not because they were low quality. Switched `scorer.py` and
`capture/caption.py` to `gemini-flash-lite-latest` (configurable via `GEMINI_MODEL` in
`.env`) - stress-tested with 25 rapid calls, zero failures, well past where 3.7-flash
broke. Also confirmed multimodal image input still works on the lite model before
switching `caption.py` over too.

**Recency-aware scoring** (request: prioritize recent, but accept older-if-still-valid):
`scorer.py` now receives the article's real `published_date` and today's date in the
prompt - previously it had neither, so "current vs stale" was being guessed purely from
content phrasing. Tier definitions rewritten so "high" explicitly allows up to ~1 week
old (or older if still fully valid/timely), "mid" covers 1-4 weeks, and discard is
reserved for genuinely off-topic/stale content, not just non-same-day. `discovery.py`'s
search window widened from 1 to 3 days to match. Verified live: three real Aug 2026 NHS
stories all correctly scored "high" with real per-article summaries.

**Tavily usage guard** (request: "check it won't overuse usage"): confirmed Tavily's
free tier is 1,000 basic-search credits/month; the 14-query daily cron uses ~420/month,
comfortable on its own, but repeated manual "Run research now" testing adds on top
fast. New `usage_tracking.py` tracks Tavily calls per calendar month
(`ApiUsageCounter` table) and both call sites (`drafting_engine/research.py`,
`research_cron/discovery.py`) now check a 900/month safety cap before searching,
leaving headroom under the real 1,000 limit rather than finding out mid-month via a
hard failure.

**Weekly-drafts layout redesign** (request: "hard to read and feels clunky"): replaced
the side-by-side horizontal-scrolling day columns (cramped 320px width, needed
scrolling to see other days) with a full-width vertical stack - one day section at a
time, top to bottom, empty days hidden entirely instead of showing empty headers.

**Readability pass** (request: "all text needs to be easy to read"): base font size set
explicitly to 16px (was relying on Radix defaults), muted text brightened from `#92A399`
to `#A3B7AC` (audit: too dim against the dark surfaces to read comfortably), draft/
compliance textareas forced to 1rem with 1.6 line-height regardless of Radix's own
size scaling.

**"Past weeks" / history view** (request: browse back and line up catch-up posts for a
thin week): new dashboard section showing everything from the last 6 weeks, any status,
grouped by week. Each row has "Reuse as new post," which copies that post's text into
the Quick Actions topic field so she can retarget it at a specific day and regenerate.

**Email reminders** (request, not in original spec): weekly personal-story nudge (her
chosen day, editable from the dashboard's "Email reminders" card, no need to touch
Windows Task Scheduler to change it) plus a Sunday-midday digest of the week's lined-up
posts. Lives in `email_engine/`: `send.py` (plain SMTP, Gmail app password by default),
`reminder.py`/`digest.py` (each idempotent per week via `job_runs`, gated internally by
day-of-week rather than relying on the Windows trigger time being exact), `settings.py`
(single-row `EmailSettings`: recipient + reminder day). Both jobs degrade to a clean
"skipped, not configured" rather than crashing when `EMAIL_ADDRESS`/`EMAIL_APP_PASSWORD`
are blank - tested for real (no credentials configured yet, confirmed correct skip
behavior, not a silent failure). `scripts/register_email_tasks.ps1` registers both as
daily-triggered Scheduled Tasks (not registered yet - same "not going live until asked"
posture as the research cron's own task). **Still waiting on real Gmail credentials**
from the user before this can actually send anything.

**Multi-page restructure** (request: "don't want everything to be on one big page"):
the single `dashboard/page.py` was split into seven focused pages under
`dashboard/pages/`, each behind its own route and its own `require_login` wrapper:

| Route | Page | Shows |
|---|---|---|
| `/` | Home | Stats overview + weekly-input upload box |
| `/review` | Review | Drafted posts, grouped by suggested day |
| `/accepted` | Accepted | Approved/published, grouped by auto-assigned week |
| `/rejected` | Rejected | Last 5 rejected only |
| `/topic-bank` | Topic Bank | Unused research findings |
| `/history` | Past Weeks | Last 6 weeks, any status, reusable as new posts |
| `/settings` | Settings | Quick actions + email reminder timing |

All seven share one `DashboardState` (normal in Reflex - state isn't tied to a single
page) and a `page_shell()` wrapper in `components.py` (header, nav bar, status banner,
`on_mount=load_dashboard`). `components.py` itself was trimmed down to shared
primitives only (`status_pill`, `chip_list`, `post_editable_body`, three post-card
variants for review/accepted/rejected); page-specific composition now lives in each
page file, not one 600-line component module.

**Review flow changed to Accept / Redraft / Reject** (request: a third option beyond
approve-or-reject): `redraft(post_id)` generates a fresh draft from the same
topic+sources and retires the old one - as `status="rejected"`,
`rejection_reason="redrafted"` - rather than adding a new status value across the whole
schema/UI for what's really just a specific kind of rejection.

**Auto-scheduling** (request: "AI automatically chooses which ones are going into this
week's lot... too many, puts them for next week"): new `scheduling.py`.
`allocate_accepted_posts()` gives every unscheduled approved/published post a
`scheduled_week` (new `Post` column, Monday-of-week date string), filling the current
week up to a 4-post cap (spec Â§1's 3-4/week) before spilling into the next week, and
the next, and so on. Runs on every `accept()` and on every dashboard page load, so it's
always caught up, not something that needs a manual trigger. Tested live: accepting a
drafted post correctly assigned it `scheduled_week=2026-08-17` (this week's Monday).

**Rejected-post pruning** (request: "only want to save the last five... after that,
delete them"): `prune_rejected_posts()` runs after every `reject()` (and after every
`redraft()`, since that's implemented as a rejection) and hard-deletes anything beyond
the 5 most recent. Tested live.

**Fully configurable email timing** (request: day AND time, independently, for both
jobs): `EmailSettings` gained `reminder_time`/`digest_day`/`digest_time` (digest was
previously hardcoded to Sunday). Both `reminder.py` and `digest.py` now check local
weekday-name AND local hour against the dashboard's settings before sending.
Consequence: the Task Scheduler trigger needs to fire hourly now, not once a day, for
an arbitrary time-of-day setting to actually be honoured -
`scripts/register_email_tasks.ps1` updated accordingly (still not registered).

**Display-label fix** (request: `personal_reflection` showing raw/underscored instead
of "Personal Reflection"): added a `humanize()` helper (`dashboard/state.py`) and
`*_label` fields (`post_type_label`, `status_label`, `tier_label`, `category_label`)
populated server-side in every `_reload_*` method, used everywhere a post
type/status/tier/category renders in the UI. The underlying stored values are
untouched - this is purely a display transform.

**Full button audit** (request: "double check every single button... make sure
everything does what it needs to do"): grepped every `on_click=`, `on_change=`, and
`on_blur=` across `dashboard/pages/*.py` and `dashboard/components.py`, cross-checked
each against the actual method list on `DashboardState` - no typos, no dead handlers,
no orphaned event names left over from the restructure. All 8 routes (7 pages +
`/login`) compiled clean and returned HTTP 200 on a live check.

**Real environment issue hit while testing this**: Ollama had silently lost all its
installed models (`ollama list` returned empty - not a code bug, something external
wiped them, possibly a system event unrelated to this project). Re-pulled `llama3` to
restore drafting capability; flagging this because if it happens again on her machine,
`ollama list` returning empty is the tell, and `ollama pull llama3` fixes it.

## Overall status

All 7 levels have working code, each tested against real APIs/data as it was built
(not just made to compile). Remaining before this is genuinely "done, not just built":
(1) the restructured multi-page UI needs actual eyes-on browser verification, same
caveat as before - no browser automation available in this environment; (2) neither
the research cron's nor the email jobs' Windows Scheduled Tasks are registered yet
(`scripts/register_scheduled_task.ps1`, `scripts/register_email_tasks.ps1` - both
written and ready); (3) email sending is inert until `EMAIL_ADDRESS`/
`EMAIL_APP_PASSWORD` are filled in `.env` with real Gmail app-password credentials.

## Full-system audit (21 Aug 2026)

Browser automation became available and was used to close item (1) above for real:
drove a real headless-Chromium session through login and all 7 pages, Accept/Redraft/
Reject, and chip editing - zero console errors. Also ran the level 4/5 pipelines live
(not fixtures) to sanity-check two things the spec never got measured against real
data: whether the topic bank actually keeps up with a 3-4 posts/week cadence (one
forced research run alone banked 21 high-tier finds - roughly ten weeks of industry-
insight supply; company-update supply is genuinely thin since WPA's own newsroom rarely
publishes daily-fresh news, which is exactly why spec Â§1's flex-to-industry-insight
fallback exists), and whether generated drafts actually match her voice profile's own
recorded stats (they did - two independently generated drafts reproduced her real
"I've learned that..." and "So, ..." patterns and 0.0 avg-hashtags-per-post unprompted).

**Real bug found and fixed - PII wasn't actually being scrubbed.** Spec Â§4 (LLM02)
calls for a PII scrub before her weekly notes reach any model; `draft.py` only ever
asked the model to *flag* sensitive content in `compliance_note`, never to remove it.
Tested with a fabricated adversarial note (a client's full name, town, rare diagnosis,
exact claim amount - synthetic test data, not a real client) and confirmed all of it
came through verbatim in `text`, plus the client's name and treatment centre landed in
`tags` (meant for public-entity @mentions) as clickable chips at the top of the review
queue. First fix attempt (stronger inline prompt rules) closed the `tags` leak and got
a correctly-triggered compliance note, but the identifying details still leaked into
`text` on re-test - llama3 8B doesn't reliably follow a scrub instruction bundled
alongside drafting/voice/sourcing rules in the same call. Real fix: split it into two
calls. `_scrub_note()` in `draft.py` is a new, narrow Ollama call whose only job is
rewriting a raw personal note to generalise name/location/diagnosis/exact figures
(with an explicit worked example in a different domain, same technique that fixed the
level 3 close-read JSON-echo bug) - `draft_post()` now runs this first whenever
`research.findings` is empty (i.e. the topic is her own raw note, not a research-backed
fact) and drafts from the scrubbed version. Re-tested the identical adversarial note
end to end: name, town, diagnosis, and exact figure all correctly generalised
("a client from the south of England", "a serious illness", "a local cancer centre",
"life-changing treatment"), `tags` correctly held only `["WPA"]`. Re-tested a normal,
non-identifying note afterward to confirm the scrub step doesn't distort content that
had nothing to scrub - confirmed unchanged in substance.

**Real bug found and fixed - unlabelled likes/comments fields.** On the Accepted page,
a published post's likes/comments entry used placeholder text ("likes"/"comments")
instead of a persistent label, so the fields went blank and unexplained as soon as a
number was typed in - every other field on the page (Hashtags, Tags, Compliance note)
has a persistent `rx.text` label above it. Added matching labels in
`components.accepted_post_card`. Verified live in-browser: labels render correctly
above both fields, values unaffected.

**Known limitation, not a bug:** the PII scrub only runs when `research.findings` is
empty, i.e. for personal-reflection-style raw notes. It intentionally does not run on
research-backed topics (industry insight/company update), since those are drafted from
public facts, not her private notes, and scrubbing them would be pointless. If a future
post type mixes her raw commentary with research in the same call, revisit this gate.

## Accepted page: filter, 4-week calendar, forward-planning notes (request, post-audit)

Three real UI issues/requests came back after using the audited build:

**Fixed - hashtag/tag input boxes clipped their own text.** `chip_list`'s `rx.input`
had no `flex`/`width`, so inside its `rx.hstack` it rendered at browser-default width
regardless of `size` - fine for a short tag, useless for anything longer. Given
`flex="1"` + `min_width="0"` so it fills the row; `Add` button given `flex_shrink="0"`
so it doesn't get squeezed. Likes/comments inputs on Accepted widened 7rem -> 9rem for
the same reason. Verified live: a 29-character hashtag now renders in full.

**Added - Accepted page status filter** (request: "a filter for looking at accepted
and looking at published ones... don't want to sift through ones that haven't been
published yet" when logging likes/comments). `accepted_status_filter` state var (all /
approved / published), applied inside `accepted_by_week`.

**Added - 4-week look-ahead calendar** (request: "select through the weeks almost like
a calendar... four weeks you can look at and plan ahead for"). `scheduling.py` gained
`upcoming_week_mondays()`/`week_dates()`; the Accepted page now shows one week at a
time via `selected_week_offset` (0-3) instead of every scheduled week stacked
indefinitely, with a button bar showing real dates for each of the 4 weeks.

**Added - forward-planning notes** (request: "I want to be able to put a note... on the
31st of October, I want it to be slightly Halloween... or there's going to be a new
statement release, I want this to be about that" - i.e. brief the drafting engine on a
future date before any topic exists). New `PlannedNote` table (migration
`dbcc2af3183a_add_planned_note_table.py`): `target_date`, `note_text`, `post_type`.
Accepted page gained a "Plan ahead" calendar grid, one card per day in the selected
week, each either showing an existing note (with a "Generate draft" button that runs
the real drafting pipeline using the note as the topic, `skip_research` gated on post
type) or a small form to add one. Real bug hit and fixed while wiring this up:
`components.day_plan_cell` originally called the plain-Python `humanize()` helper
directly on a reactive `Var` inside a `rx.foreach` render function - `humanize()`'s
`if value else value` branch can't evaluate a `Var`'s truthiness
(`VarTypeError: Cannot convert Var ... to bool`), the same class of bug the rest of the
dashboard already avoids by pre-computing `*_label` fields server-side. Fixed the same
way: `PlannedNoteView` gained `post_type_label`, populated in `_reload_planned_notes`
instead of calling `humanize()` at render time.

Tested live end to end, not just compiled: saved a note ("Halloween-themed post about
workplace wellbeing spooky season tie-in") on a real date, confirmed it persisted
through a page reload, clicked "Generate draft", and got back a real draft that
actually reflected the note's brief (a Halloween-party/wellbeing post, in her voice,
`suggested_day` correctly set to match the note's date) - the planning note reliably
steers what the drafting engine writes, not just decoration on the calendar.

## Task Scheduler + Gmail: gone live (request, post-audit)

All three Windows Scheduled Tasks are registered and confirmed `Ready`
(`WPA Daily Research Cron`, `WPA Weekly Reminder Email`, `WPA Weekly Digest Email`).
Real bug found and fixed in `scripts/register_email_tasks.ps1`: `-RepetitionDuration
([TimeSpan]::MaxValue)` formats to `P99999999DT23H59M59S`, which Task Scheduler's XML
schema rejects outright (`HRESULT 0x80041318`) - confirmed live, the task silently
never got created despite the script printing a "Registered" success line. Root cause
of that false success line: `Register-ScheduledTask`'s CIM errors don't respect
`$ErrorActionPreference = "Stop"` on their own - both scripts now pass
`-ErrorAction Stop` explicitly on the `Register-ScheduledTask` call itself. Fix for the
duration bug: build the trigger without `-RepetitionDuration`, then set
`$Trigger.Repetition.Duration = ""` after creation - the documented way to mean
"repeat indefinitely," confirmed by inspecting the resulting CIM object. Also worth
noting for future debugging: `Register-ScheduledTask` needs a genuinely elevated
PowerShell window - a plain window that merely doesn't error can still fail with
Access Denied, so verify with
`([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)`
before assuming elevation.

Gmail app-password credentials are in `.env`; `send_email()` confirmed working via a
real live send. Both scheduled tasks were also triggered manually
(`Start-ScheduledTask`) to prove they actually run, not just that they exist - research
cron correctly no-op'd (already run today), reminder email correctly skipped with a
specific reason (`"it's 15:00, reminder time is 09:00"`) rather than erroring.

**Weekly reminder now suggests rotating prompt ideas** (request: "give a few
recommendations of some things it could be about... switch them up each week...
doesn't request that the next week as well"). `PROMPT_POOL` in `reminder.py` holds 10
prompt ideas; each send picks 3, excluding whatever 3 were shown last time
(`EmailSettings.last_reminder_prompts`, JSON, updated only after a successful send).
She's never told to use one - the email frames them as optional. Tested live: sent two
consecutive reminder emails (`--force` twice) and confirmed zero overlap between the
two sets of 3. Real side-effect caught and fixed after testing: force-sending marks
`job_runs` as sent, which would have made the *real* scheduled task silently skip for
up to 6 days once the actual configured day/time came around - reset `job_runs` for
both email jobs (and `last_reminder_prompts` back to empty) after testing so the live
schedule starts clean, not mid-test-state.

**Full visual audit, all 7 pages, after a user-reported spacing bug that didn't
reproduce**: screenshotted every page in a clean headless browser (no extensions) -
everything rendered correctly, no clipped text, no overlapping elements. The reported
issue was very likely a browser extension icon (e.g. dictation/accessibility) that
injects itself onto a focused input field - not something this app renders.

**Reminder email now checks whether she's already sent something in this week**
(request: "if something is already added into the personal section, I don't want that
personal nudge to go out... rather than a nudge to do it, a nudge to go check it
quickly"). New `scheduling.current_week_start()` gives a tz-aware Monday-00:00 boundary
to filter `Post.created_at` against; `reminder._existing_personal_post_this_week()`
looks for a non-rejected `personal_reflection` post created since then. Branches on
what it finds: nothing -> the normal ask-for-a-story nudge (with rotating prompts, see
above); `drafted` -> a short "it's already in Review waiting for you" nudge with an
excerpt; `approved` -> "already accepted, just needs posting" with an excerpt;
`published` -> nothing to nudge about, so no email sends at all (job still marks itself
as run, so it doesn't re-check every hour for the rest of the week). A rejected post
doesn't count as "already there" - if it didn't work out, she should still get asked
for a new one. Tested live, all four branches: inserted a test post and walked it
drafted -> approved -> published, force-sending the job at each stage and confirming
the email (or absence of one) matched - then deleted the test post and reset
`job_runs`/`last_reminder_prompts` so testing didn't leave the live schedule in a
mid-test state.

## PII scrub hardened - a second, independent check, not just a doc caveat

The handoff pack had documented "PII scrub isn't 100% automatic, review before
accepting" as a known limitation - correctly flagged, but a caveat isn't a fix.
Reworked `draft.py`'s scrub into two layers on top of the original single rewrite
call, since "worked in testing" on an 8B local model isn't the same as "reliable every
time":

1. **Deterministic money redaction** (`_redact_money`, a regex, not a model) - applied
   to the scrubbed note before drafting *and* to the final draft text on the way out.
   An exact monetary figure is unambiguous, so this layer cannot fail to catch one
   regardless of what the LLM did upstream.
2. **A second, independent LLM call verifies the first one's work**
   (`_still_identifying`) - checking a narrow yes/no question ("does this still name a
   real person, a specific place, or an exact figure?") is far more reliable for a
   small model than getting the original rewrite exactly right in one pass. If it
   still finds something, `_scrub_note` retries the rewrite once with that pointed out
   explicitly, then verifies again.

If it's still unresolved after the retry, `draft_post` now overwrites
`compliance_note` with an unmissable `"PII CHECK FAILED..."` message instead of
whatever the drafting call would have said - so an unresolved case can never quietly
read as "No compliance concerns identified."

Tested live: re-ran the exact Sarah Thompson/Bristol/leukaemia/£45,000 adversarial
case end to end - fully scrubbed on the first pass this time (no name, no town, no
diagnosis specifics, no figure). Also unit-tested `_still_identifying` in isolation
against a deliberately unscrubbed sentence (correctly returned `True`) and a properly
scrubbed one (correctly returned `False`), and `_redact_money` against both `£` and
`$` figures, to confirm the safety net itself works, not just the happy path.

## Email tasks were firing hourly - fixed to once a day (user-reported)

The hourly-poll design (chosen so an arbitrary day+time setting could be honoured
without hand-editing Task Scheduler) turned out to be a real nuisance in practice -
she was seeing both email tasks fire every hour, all day. Confirmed live via
`Get-ScheduledTask`: the reminder task's trigger was a repeating "Once" trigger with
an hourly `Repetition` pattern, exactly as designed - working as built, but the design
itself was wrong for daily use.

Fixed properly rather than just reducing frequency: since `reminder_time` and
`digest_time` are two independent settings already, and each job is its own Scheduled
Task, each task's trigger can just fire once a day at exactly that job's configured
time - no polling needed at all. `register_email_tasks.ps1` now registers two
`-Daily -At <time>` triggers instead of one shared hourly one.

The remaining gap: if she changes the time in the dashboard, the *stored* setting
changes but the *live Windows trigger* wouldn't move on its own, and the two would
silently drift apart. Closed this in `email_engine/settings.py`:
`save_email_settings` now also calls `schtasks /Change /TN "<task>" /ST <time>` for
both tasks after saving - best-effort (wrapped so a failure here, e.g. task not
registered yet, never blocks the actual settings save).

**Could not apply the live fix myself**: `Register-ScheduledTask`/`schtasks /Change`
both require genuine elevation, confirmed via a live "Access is denied" when tried
from a non-elevated session (`IsInRole(Administrator)` returned `False`). The code fix
is committed and correct, but **the already-registered hourly tasks on this machine
need `scripts/register_email_tasks.ps1` re-run once from an elevated PowerShell
prompt** to actually replace them - `-Force` is already set so it overwrites the old
hourly-trigger tasks cleanly, no manual unregister step needed first.
