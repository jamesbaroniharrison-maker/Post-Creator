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

## Login removed (2 Sept 2026)

Request: "it's locally hosted, removed the login page." `reflex_local_auth` is fully
out - no import, no `/login` route, no logout button, and the `localuser`/
`localauthsession` tables are dropped (migration `38d872cfac60`, applied - confirmed
live via direct sqlite3 query that both tables are gone). `scripts/create_account.py`
deleted (nothing left to create an account for) and `reflex-local-auth` dropped from
`requirements.txt`. `Start Content Engine.bat` now opens `/` instead of `/login`.

If this ever needs to be reachable beyond localhost (a different machine, a real
network), auth needs to come back before that happens - there's currently nothing
stopping anyone who can reach the port from using the dashboard.

## Month planning view + per-week catch-up button (2 Sept 2026)

Request: "plan a month of posts out, not just a week... have a button to draft for
that specific days posts... a draft this weeks post button if for whatever time they
havent come up." Investigated first, before building: re-editing already worked on
Review and the Accepted page (including published posts) via `post_editable_body` -
that part needed no change, just confirming and documenting it in `HOW TO USE.txt`,
since it wasn't obviously discoverable.

The actual gap was the "Plan ahead" calendar only ever showed one week at a time,
paged via the same `selected_week_offset`/`week_selector_bar` that also filters the
Accepted-posts list above it - so planning and the accepted-post filter were coupled
for no real reason. Decoupled them: `_reload_planned_notes` now loads across the full
4-week horizon unconditionally (not tied to a selected week), and a new `month_plan`
computed var (`WeekPlanView` per week, each holding its 7 `DayPlanView` days) replaces
the old single-week `week_plan`. `week_selector_bar`/`selected_week_offset` still exist,
now scoped purely to the Accepted-posts list.

New per-week "Fill this week" button (`DashboardState.fill_week`, one instance per
week section in the calendar) - request confirmed directly: pulls from the best
unused topic bank rows first, falls back to a rotating prompt from
`email_engine/reminder.py`'s `PROMPT_POOL` (reused rather than duplicated) if the
bank's empty, generating however many posts a week is short of `WEEKLY_CAP`. A new
module-level `_draft_from_bank_row` helper factors out the bank-drafting logic
previously only inline in `generate_from_bank`, so both share it rather than
duplicating the research/post-type/mark-used steps.

Verified live: full `reflex run` boot, `/accepted` compiles and returns 200 with the
new month view. Directly unit-tested the underlying query logic and
`_draft_from_bank_row` outside the Reflex event wrapper (background events are awkward
to invoke standalone) - confirmed the weekly-committed-count query, the topic-bank
query, and the draft-and-mark-used flow all work end to end against the real database.

## Full UI overhaul (3 Sept 2026)

Fully specified via two documents provided directly and now checked into the repo
root: `design-reference.html` (a static mockup - colours, buttons, empty state, a full
redesigned Home page) and `UI-OVERHAUL.md` (the section-by-section instructions).
Executed in the prescribed order: tokens, then shared components, then pages.

**Tokens** (`assets/design_tokens.css`): new warm dark palette (`bg #14110F`, `surface
#1C1815`, `surface-2 #221D19`, `border #2E2822`, `border-strong #3D362E`, `text
#F2EDE4`, `text-muted #8C8479`), two accents with two jobs that are never swapped -
gold (`#C9A66B`) for data (stat numbers, focus rings), terracotta (`#BF6E4E`) for
actions (primary buttons, active nav underline, today's calendar-card border).
`color_scheme="bronze"` stays unchanged everywhere in the Python code (avoided a
much larger diff) - it's remapped to the real terracotta hex via the same
`--bronze-*` CSS custom-property override trick already used for `--gray-*`/
`--accent-*`, confirmed live rather than assumed to work.

**Shared components** (`dashboard/components.py`): `nav_bar` rebuilt (no background
box on the active tab, 2px terracotta underline instead); new `empty_state()` used on
Review/Rejected/Topic Bank/Past Weeks in place of bare muted text; `stat_card` gained
a `ghost` param for Home's dashed/transparent derived-metrics row; `accepted_filter_bar`
rebuilt as a real segmented control (one bordered container, no gaps) so it reads as a
different kind of filter from the week-selector pills above it; `day_plan_cell` gained
a "Notes" label and a today's-date highlight.

**Real bug hit and fixed while verifying this, not just assumed to work**: the
today's-date border on the planning calendar rendered with zero visible effect the
first time - `.rt-Card`'s own `border: ... !important` CSS rule silently defeated a
plain inline `border=` prop on the same component (an inline style loses to any
`!important` rule regardless of specificity). Fixed with a dedicated
`.rt-Card.hud-card-today` class (two combined class selectors beat the bare
`.rt-Card` rule on specificity) instead of an inline override - confirmed fixed via a
live headless screenshot showing the terracotta border actually rendering on today's
card.

**Home page**: stats split into a labelled "This week's activity" solid row plus a
dashed ghost row, matching the reference; the two separate note/upload flows (each
with their own button) merged into one "Note or upload" section with a single "Draft
this post" button - new `DashboardState.submit_weekly_input()` branches server-side on
whether there's note text or an uploaded file, delegating to the existing
`submit_text_upload`/`handle_upload` handlers rather than duplicating their logic.

**Settings page**: the one "Quick Actions" card with three unevenly-sized sections
split into three actual cards in a grid; every input gained a real label instead of
placeholder-only text; a divider added between the two independent email-timing
settings; the "Save" button resized/re-styled to match the primary buttons used
elsewhere on the page.

Verified with real headless-Chromium/Edge screenshots (`--headless=new
--virtual-time-budget=8000` so the SPA actually hydrates before capture, a technique
now established in this project - see the "visual design/polish" entry above) across
all 7 pages, not just a compile check - caught the today-border bug this way, and
confirmed a separately-observed odd heading colour on one Review-page screenshot was a
one-off capture glitch (re-screenshotted, didn't reproduce) rather than a real issue.

## Weekly plan template, holidays, "Plan this week", topic-day linking, Statistics (3 Sept 2026)

Request (dictated, parsed carefully): choose which post type goes on which day of the
week including a "no post" option; recognise holidays and suggest a themed post;
a button that actually drafts the coming week's posts automatically; the ability to
click a topic bank finding and attach it to a specific day; a Statistics page. One
fragment of the dictation ("Guitar project") didn't parse into anything actionable and
was left alone rather than guessed at.

**New schema**: `WeeklyTemplate` (single-row settings, one post-type-or-"no_post" field
per weekday plus `recommend_holidays`) and `PlannedNote.source_bank_id` (FK to
`topicbank`, set when a note came from linking a bank row rather than being typed by
hand). Migration `d49a5125d289` - real bug hit and fixed while applying it: the
auto-generated migration used an unnamed FK constraint
(`batch_op.create_foreign_key(None, ...)`), which SQLite's batch-alter mode rejects
outright (`ValueError: Constraint must have a name`) - confirmed live, and the
partially-applied migration left an orphaned `weeklytemplate` table with
`alembic_version` never bumped, so the table had to be dropped by hand before
re-running the corrected (named-constraint) migration.

**Holidays** (`holidays.py`, new module): a fixed-date lookup table only (Christmas,
Halloween, New Year, etc.) - deliberately not a full holiday-calculation library,
since variable-date holidays (Easter, bank holiday Mondays) need real date arithmetic
that isn't worth the complexity for a nudge feature.

**"Plan this week"** (`DashboardState.plan_week`, one button per week section
alongside the existing "Fill this week"): reads the weekday template day by day - a
holiday match overrides a "no_post" day into a personal reflection with the holiday
angle as its topic, but never touches a day that already has a note. For each day it
does plan, it creates the `PlannedNote` and immediately drafts it (best unused topic
bank row for ai/market days, a rotating `PROMPT_POOL` prompt for personal days),
landing in Review like everything else. Verified live end to end against the real
database and real Ollama/Gemini calls - correctly drafted 4 days, skipped 3 "no_post"
days, 0 failures. (Along the way, discovered 67 real, legitimate topic-bank rows and
several real draft posts had accumulated across earlier sessions without being
cleaned up - not a bug, just testing residue - cleaned up test-only rows/posts while
restoring the real bank rows' `used` flags rather than deleting real research data.)

**Topic Bank → day linking** (`DashboardState.link_topic_to_day`): genuine
cross-page drag-and-drop isn't practical to build reliably in Reflex, so this is the
practical equivalent - pick a target date once at the top of Topic Bank
(`link_target_date`, a native `<input type="date">`), then click "Link to day" on any
finding; it creates/overwrites that date's `PlannedNote`, pointed at the bank row.
Verified live: linked note showed up correctly on the Accepted page's calendar with
the real bank summary, the right post type, and a working "Generate draft" button.

**Statistics page** (`/statistics`, new nav item): breakdowns by post type, status,
and every CPIO/THBM rotation variable (funnel stage, hook posture, length, structural
format, media pairing), plus posts-per-week for the history window - gold horizontal
bars (`stat_bar_row`/`stat_breakdown_card` in `components.py`), reusing the same
all-posts query `_reload_stats` already ran rather than hitting the database twice.

**Known verification gap, flagged rather than glossed over**: the Topic Bank page's
own async-loaded data (`bank_rows`) did not visibly render in three separate headless
screenshots, including after a fully clean server restart on fresh ports - despite
directly testing the exact same query and `BankView`-construction logic standalone and
confirming both work correctly against the real database every time (45+ qualifying
rows, `BankView` objects built without error). Other pages' async data (the Accepted
page's linked-note calendar cell, in the same session) rendered correctly under the
same capture method, so this doesn't look like the general "SPA hasn't hydrated yet"
timing issue already known and worked around elsewhere - but it wasn't fully
root-caused either. Worth a real look in an actual browser (not headless) before
trusting the Topic Bank page's initial-load rendering; if it reproduces there too,
start by checking whether `bank_rows`'s reactive update is actually reaching the
frontend (browser dev tools' Network/WS tab) versus a rendering issue in
`topic_bank_page`'s `rx.cond`.

## Login restored for remote (Tailscale) access (3 Sept 2026)

Request: reachable from a phone while away from the house. The "Localhost only" hard
rule doesn't change - a Tailscale mesh keeps the dashboard off the public internet -
but "reachable only from this one machine" (the assumption login removal was built on,
2 Sept 2026 entry above) stops being true the moment another device can reach it over
Tailscale, so login had to come back first.

Reverted the login-removal commit's changes deliberately, not blindly: re-added
`reflex_local_auth` (import, `/login` route, `@require_login` on all 7 original pages
plus the new `/statistics` page that didn't exist when login was first removed, the
"Log out" button in `page_shell`), restored `scripts/create_account.py`, and put
`reflex-local-auth==0.5.0` back in `requirements.txt`. New migration
`5bcca3137f6e_restore_local_auth_tables` recreates `localuser`/`localauthsession` with
the exact same columns/indexes the original drop migration removed - applied and
confirmed live via direct sqlite3 query that both tables exist again.

**Real bug hit while installing the dependency**: `pip install reflex-local-auth==0.5.0`
pulled in Reflex 0.9.10 as a transitive dependency, silently upgrading past the
project's pinned 0.9.8 - confirmed via `pip show`. Re-ran `pip install "reflex[db]==0.9.8"`
afterwards to force it back down; reflex-local-auth 0.5.0 is the same version that
worked against 0.9.8 before removal, so this isn't a new compatibility risk.

Verified live: full `reflex run` boot compiled clean (34/33 - the `/login` route now
counted), backend already binds `0.0.0.0` by default (no config change needed for
Tailscale to reach it), `/ping` returns `"pong"`, and the Socket.IO event endpoint
responds. Could **not** get a clean headless-Chromium screenshot of the client-side
redirect to `/login` - it stalled on Reflex's own "Loading..." splash even at a 14s
`--virtual-time-budget`, with no socket.io connection attempt visible in the browser's
own console log. This is the same category of unresolved headless-capture limitation
already flagged for the Topic Bank page above, not a new server-side bug - the backend
health checks all passed, so treat it as an environment quirk of headless capture in
this setup, not a reason to distrust the auth gate itself. Confirm the actual login
prompt shows up in a real browser tab once you're back at the machine.

**Not done, and can't be done remotely**: actually installing and pairing Tailscale.
`winget install --id Tailscale.Tailscale` needs a UAC elevation click on the physical
screen - it stalled waiting for that with no way to approve it from a phone - and even
once installed, `tailscale up` opens a browser tab to authenticate against your
Tailscale/Google account, plus the Tailscale app needs installing and logging into on
the phone separately. All genuinely manual, one-time steps for whoever's at the
keyboard. Once done: create your dashboard login (`python -m scripts.create_account
--username you --password "..."` from `linkedin_content_engine/`, venv active), then
your phone can reach `http://<tailscale-machine-name>:3000/login` from anywhere.

## Post-type dropdowns showing raw snake_case (3 Sept 2026)

Request: "I don't like the personal_content no_post... make them plain text so it
looks better." Most of the app already humanized these (`post_type_label` on
`PostView`/`DayPlanView`), but Reflex's high-level `rx.select(list[str], ...)` only
supports one string as both the option's value and its displayed label - so anywhere
a select was built straight from `POST_TYPES`/`DAY_TEMPLATE_OPTIONS`, the raw value
("no_post", "personal_reflection") was what showed up in the dropdown itself.

New `type_select()` helper (`dashboard/components.py`) rebuilds the same
trigger/content/root structure `HighLevelSelect.create` uses internally, but with
`rx.select.item(humanize(opt), value=opt)` instead - `humanize()` already existed
(used elsewhere for badges/labels), this just wires it into the select itself. Applied
everywhere `POST_TYPES`/`DAY_TEMPLATE_OPTIONS` fed a raw select: the Weekly Plan
Template's 7 day pickers, the quick-generate post type, the Home page upload post
type, and the per-day note-draft post type on the planning calendar. Confirmed in the
compiled output, not just assumed: `RadixThemesSelect.Item({value:"no_post"},"No
Post")` - value stays the raw string the backend expects, label is humanized.

## Daily research cron: a real silent failure, found and fixed (3 Sept 2026)

Not a request - went looking for the highest-leverage next improvement and found the
7am scheduled run that same morning had actually failed: `Get-ScheduledTaskInfo`
showed `LastTaskResult = 3221225786` (`0xC000013A`, `STATUS_CONTROL_C_EXIT` - Task
Scheduler force-killing the process), and because `research_cron/pipeline.py` only
commits the topic-bank rows it found in one batch at the very end of the run
(`_set_last_run`/`session.commit()` both happen after the full query loop), a run
that gets killed partway through saves nothing at all - and nothing anywhere would
have shown this had happened. Task Scheduler doesn't capture a task's stdout/stderr by
default, so the only trace was that one `LastTaskResult` field, which nobody was
checking.

Ran the cron manually to get real numbers rather than guess: **10 minutes**
end-to-end, stored 15 high-tier / 12 mid-tier findings, 28 duplicates skipped, 0
errors. So the old 30-minute `ExecutionTimeLimit` wasn't chronically too tight - this
looks like a one-off slowdown (likely Gemini free-tier scoring calls running slow or
getting throttled; each finding gets its own scoring call with a 60s timeout) - but
with zero visibility, a rare fluke is exactly as invisible as a systematic problem
would be.

Three-part fix, not just "raise the timeout":
- **Logging**: `research_cron/run.py` now writes to `research_cron.log` (next to
  `rxconfig.py`, gitignored) with an explicit `STARTED` line and a `FINISHED: {...}`/
  `FAILED` line - a start with no matching finish is itself diagnostic evidence of a
  timeout-kill, not just silence.
- **Headroom**: `scripts/register_scheduled_task.ps1`'s `ExecutionTimeLimit` raised
  30 -> 90 minutes. This job isn't time-sensitive (nobody's waiting on a 7am cron), so
  there's no real cost to generous headroom instead of tuning close to the observed
  normal duration. **Not yet applied to the live registered task** - updating it needs
  the same elevation `Register-ScheduledTask` always has (confirmed live:
  `Set-ScheduledTask` failed with "Access is denied" from this non-elevated session) -
  re-run `register_scheduled_task.ps1` from an elevated prompt to pick it up.
- **Dashboard visibility**: new `DashboardState._reload_job_status()` reads
  `JobRun.last_run_at` for `daily_research` (already the pipeline's own
  once-per-day-guard field, and only ever written on a successful full completion -
  a genuine "last success" signal, not "last attempt") and shows it on the Settings
  page next to "Run research now," flagged red/"overdue" past 36 hours old. Confirmed
  in the compiled output.

Manually running the cron with `--force` during this investigation also means today's
research wasn't actually lost - the topic bank has today's real findings now, just
about 6 hours later than the scheduled 7am run would have delivered them.

## New Voice page - the voice profile had no dashboard flow at all (3 Sept 2026)

Asked for the next highest-leverage improvement again. Went looking, and found
something more fundamental than the cron fix above: the voice profile that every
single draft is generated against had **no way to update it from the dashboard at
all**. `voice_engine/ingestion.py`'s `add_sample()` and `voice_engine/run.py`'s
`build_and_save_profile()` were CLI-only, invoked directly against `python -m
linkedin_content_engine.voice_engine.run` - not referenced anywhere under
`dashboard/`. Checked the live database: `voicesample` is empty, but `voiceprofile`
holds one row generated 2 Sept 2026 from 5 placeholder/test samples (visible
keyness terms like "unlearning," "boilerplate" from the placeholder corpus used
during the repurposing pivot's testing, not James's real writing). So every draft
since then has been "voice-matched" against fake samples, with no way to fix that
short of editing the database directly or running a CLI script by hand - the core
premise of the whole system (voice-matched drafting) has quietly not been true.

New `/voice` page: a "Your samples" card (list with delete, "Regenerate voice
profile" button) and an "Add a sample" card (paste text, defaults `source_type` to
`linkedin_post` - `audio_transcript` samples still come through the existing
capture/transcription pipeline, this is specifically for pasting past posts).
`DashboardState._reload_voice()` loads both `VoiceSample` rows and the latest
`VoiceProfile.generated_at` for a status line; `add_voice_sample`/
`delete_voice_sample` are plain events, `regenerate_voice_profile` is a background
event (the close-read step makes a real LLM call, same reasoning as
`run_research_now` being background).

Verified for real, not just compiled: ran `add_sample()` directly against the venv
python and confirmed the row landed and `get_all_samples()` picked it up, then
deleted it again (throwaway text, not a real sample - didn't want to seed more
placeholder data into the exact table this feature exists to let James curate
properly). Compiled clean (36/35 routes, one more than before for `/voice`) and
confirmed in the compiled output that "Your samples," "Add a sample," and
"Regenerate voice profile" all render.

**Not done - needs James's own real writing**: the page works, but nobody has
pasted real samples in yet, so the profile is still the placeholder one until he
does. Worth flagging directly rather than implying this is now "fixed" end to end -
the tooling gap is fixed, the actual data gap isn't (only he can fix that one).

### Aside: a real environment mistake made and caught while building this

Every `pip install`/`python -m reflex run` I'd run earlier this session (the login
restoration, the dropdown fix) used whatever `python`/`pip` PATH resolved to -
Windows' global `pythoncore-3.14-64` install, **not** `venv/Scripts/python.exe`,
the interpreter `Start Content Engine.bat` and the scheduled tasks actually use.
Caught it here because a script importing `dashboard/state.py` (which now imports
`voice_engine`) failed with `ModuleNotFoundError: wordfreq` under global Python but
worked under the venv. Checked whether this had done any real damage: it hadn't -
`venv` already had `reflex==0.9.8` and `reflex-local-auth==0.5.0` correctly
installed (apparently never actually uninstalled from the venv when the login-
removal commit dropped the import and the requirements.txt line, just left
present-but-unused), so the real app was never broken by this. But every verification
boot this session before this point was technically run against the wrong
interpreter, and the earlier `pip install reflex-local-auth==0.5.0` /
`pip install "reflex[db]==0.9.8"` calls installed into global Python unnecessarily
(harmless - just untracked, unneeded packages sitting in the global site-packages,
left alone rather than risk an unrelated uninstall). Switched to invoking
`venv/Scripts/python.exe` explicitly for everything from this point on - the register
scripts and Task Scheduler entries were never affected since they always pointed at
the venv correctly.

## Example drafts generated for review (3 Sept 2026)

Asked to see 3 example posts of varying lengths - the database had 0 posts (cleaned
of test data after earlier verification rounds), so generated 3 real ones through
the actual pipeline: 2 from real topic-bank findings (a `TEMPO` FDA AI-pilot story
and a US/EU AI-regulation-divide story) and 1 personal reflection from the prompt
pool, left sitting in Review like any normal draft rather than being deleted as
test data - genuinely postable if James wants them.

**Real bug hit along the way, not yet fixed**: the second bank-sourced draft on the
first attempt threw `json.decoder.JSONDecodeError` - the local model returned
malformed JSON (`Expecting property name enclosed in double quotes`) and
`draft_post` (`drafting_engine/draft.py`) has no retry/repair for a malformed
structured-output response, unlike the retry logic already built for the audit-gate
and privacy-scrub calls. Worked around it by retrying the generation (succeeded
second time - the topic bank row hadn't been marked `used` yet since the mark-used
step only runs after a successful draft, so nothing was lost). Left unfixed since
it wasn't today's highest-leverage item, but worth doing the same "split into a
narrow retry" treatment that already fixed the JSON-echo and PII-scrub reliability
bugs (see the engineering lessons list near the top of this file) - flagging here
so it doesn't get lost.

## Found and fixed why drafts kept repeating "The thing is..." (3 Sept 2026)

Request: "I don't have a fan of those. They are repeating phrases too much... I would
repeat things but that doesn't mean every post would include that. I want it to feel
more like me." Traced it to a real, specific root cause, not just tone-tweaked the
prompt and hoped: `persona.py`'s `CHARACTERISTIC_LANGUAGE` block listed 7 "discourse
openers" (including `"The thing is..."`) and 8 "conversational bridges" as one static
prose string, dumped into the drafting prompt **in full, every single call**. The
model wasn't sampling among them - it was defaulting to whichever read as the
safest/most generic one, "The thing is...", in roughly two of the three example
drafts shown.

This is the exact same failure mode `draft_post`'s existing comment already documents
for `PERSONA_EXEMPLARS` a few lines below it: "with all 4 persona exemplars shown
every call, the model repeatedly plagiarised one almost verbatim... a smaller,
rotating sample gives it less of a single complete example to copy wholesale." That
fix (`random.sample`, 2 of the pool per call) was already in place for the exemplars -
the discourse-opener/bridge list just never got the same treatment.

Fix, mirroring the proven pattern rather than inventing a new one: `persona.py`'s
`CHARACTERISTIC_LANGUAGE` string is now two real lists, `DISCOURSE_OPENERS` (7) and
`CONVERSATIONAL_BRIDGES` (7), plus `CHARACTERISTIC_VOCABULARY` (unchanged, prose - the
vocabulary list wasn't the repetition problem). New `draft.py::_sample_characteristic_
language()` samples 3 of each per call and adds an explicit instruction the static
version never had: "most posts shouldn't use any of them at all, and none of them
should show up in back-to-back posts." Verified for real: called the sampler directly
three times and confirmed a different subset each time, then ran a full draft through
`generate_and_save_draft` end to end (topic: a debugging-weekend personal reflection) -
it landed cleanly with no exception and didn't open with "The thing is." One clean run
isn't proof the phrase can never recur (it's still one of 7 openers, still shown some
of the time by design), but it's no longer the same 15 words handed to the model
unconditionally on every single call, which was the actual mechanism causing the
overuse. Compiled clean afterward (36/35 routes, unchanged from before this fix).

This is a real corpus-adjacent fix but a separate lever from the corpus itself:
answered James's direct question ("how can I improve the corpus") by pointing at the
new `/voice` page from the entry above - paste 8-15 real past posts in, then hit
"Regenerate voice profile." More real samples means richer, more varied `few_shot_
examples`/`llm_close_read` output competing for space in the prompt against the
hand-authored `PERSONA_EXEMPLARS`, which is a second, independent way the "sounds
like a placeholder, not like me" problem gets better over time - this fix and a
richer corpus both push in the same direction, neither replaces the other.

## Retry on malformed-JSON drafts (3 Sept 2026)

Picked off the top of a "what else can be done" menu - the JSONDecodeError bug
documented in the "Example drafts generated for review" entry above, flagged there
as found-but-not-yet-fixed. `draft_post`'s two generation call sites (the initial
draft, and the audit-gate-failure retry) both called `_chat` and parsed its output
inline with zero resilience - a malformed JSON response crashed the whole draft,
same failure mode already fixed for the audit-gate and privacy-scrub calls but never
applied here.

New `_chat_and_parse_draft(system_prompt, user_content, retries=2)` wraps the
call-and-parse step, retrying (plain re-call, same prompt - local models are
stochastic enough that a second attempt usually just succeeds, confirmed by this
exact bug requiring a second manual run to succeed) on `json.JSONDecodeError` or
`pydantic.ValidationError`, raising only after exhausting retries. Both call sites in
`draft_post` now go through it instead of the inline `_chat`/`json.loads`/
`model_validate` sequence.

Verified for real, not just by reading the code: mocked `_chat` to fail once then
return valid JSON - confirmed it retried and returned the correct result (2 calls
made); mocked it to always fail - confirmed it correctly raises after exhausting
retries (3 attempts: 1 + 2 retries), rather than retrying forever or swallowing the
error silently. Then ran one real draft end to end through the actual pipeline
(`generate_and_save_draft`, no mocking) to confirm nothing broke - landed cleanly.

## Real Tailscale + email + the actual Topic Bank bug, finally closed (3 Sept 2026)

Request: "do everything that you can" - a follow-up to an earlier "what else can be
done" menu. Four items, each pushed as far as it could genuinely go without James at
the keyboard:

**Tailscale finished on its own**: the `winget install` that looked stalled on a UAC
prompt earlier actually completed in the background. Ran `tailscale up`, got a
one-time device-auth link, and - since that link only needs a browser, not the PC -
sent it straight to James to open on his phone. Confirmed both sides came up: PC is
`desktop-a2etve9`/`100.95.165.19` on the tailnet, phone (`iphone-13-pro`) later showed
as `active` in `tailscale status`. Created the dashboard login (`james`, initially a
generated password, later changed to one James chose) and verified `curl` against the
Tailscale IP hit both frontend and backend with 200s before handing over the link -
confirmed the frontend derives its backend URL from `window.location.hostname`
(`.web/utils/state.js:110`), not a hardcoded localhost string, so this works correctly
regardless of which non-default port a given `reflex run` lands on.

**Email settings actually finished**: `.env` already had real SMTP credentials sitting
unused - the `emailsettings` table just had no row, because nobody had ever clicked
Save on the dashboard's Email Reminders card. Called `save_email_settings()` directly
with the recipient set to James's own email and the code's own built-in defaults
(Friday 9am reminder, Sunday 12pm digest - already the model's defaults, not invented
here). Verified for real, not just assumed configured: sent an actual test email
through `send_email()` using the live credentials - delivered successfully.

**The real Topic Bank bug, found at last**: every earlier attempt to verify this page
predates login being added back, or predated a database with any real posts in it -
so the page was never actually reachable in a state that could reveal the real
problem. Installed Playwright (`pip install playwright`, `playwright install
chromium`) in the venv specifically to script a real login (fill the form, click
Sign in) followed by a real page-by-page check - something no CLI screenshot tool
could do once login existed. That surfaced the actual error, visible in the page body
itself: **"Couldn't load the dashboard (can't compare offset-naive and
offset-aware datetimes)."** `load_dashboard`'s try/except was silently swallowing a
real Python `TypeError` and showing its generic fallback message instead - on every
single page, not just Topic Bank. It was never a rendering/hydration issue.

Root cause: every datetime field in this codebase is written with
`datetime.now(timezone.utc)` (aware), but SQLite has no real timezone-aware storage
type, so SQLAlchemy reads every one of them back **naive**. Any code that compares a
DB-read datetime directly against a freshly-made aware one crashes. This had been
latent since the "Weekly plan template... Statistics" batch introduced
`_reload_full_stats`'s week-cutoff filter (`if p.created_at >= cutoff`) - it just
never had a *non-empty* `all_posts` list to actually execute against until the 5
example drafts generated a few turns ago gave it something to compare.

New `linkedin_content_engine/utils.py::as_utc(dt)` - a naive datetime read from the DB
was written as UTC, so treating it as UTC on the way back out is correct, not a
guess. Applied everywhere a DB-read datetime gets compared/subtracted against another
Python datetime object (SQL-level `.where(sqlmodel.col(...) >= x)` filters were
already safe and untouched - the bug is specifically about two already-loaded Python
datetime objects meeting each other):
- `dashboard/state.py`: `_reload_stats`'s review/publish-time averages, `_reload_full_
  stats`'s week-cutoff filter, and `_reload_job_status` (simplified to use the shared
  helper instead of its own inline guard added earlier today).
- `email_engine/reminder.py` and `email_engine/digest.py`: both `_already_sent_this_
  week` functions had the identical bug - would have crashed the very first time
  either scheduled email job ever found a matching `JobRun` row, i.e. on its second
  real send. Found and fixed *before* it could ever fire for real, not after.

Verified for real end to end: restarted the dev server, ran the same Playwright script
against it - zero "Couldn't load" errors on any of 9 pages, Topic Bank showing its
real 18+ banked findings with correct tier/category badges and working buttons
(screenshot confirmed), and Statistics' "Posts per week" card - the exact code path
touched - populated correctly instead of silently staying empty.

**Still can't be done remotely**: the elevated re-run of `register_scheduled_task.ps1`
(needs a UAC click), and the PC reboot that would clear out this session's own pile of
stuck zombie dev-server processes on ports 3000-8011 (a full reboot is a real
disruptive action on James's machine - not done without asking first, unlike
everything else in this entry which was either fully reversible or explicitly
requested).
