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

Level 3: code complete, awaiting her real corpus. Pipeline lives in
`wpa_content_engine/wpa_content_engine/voice_engine/`: `ingestion.py` (writes to
`voice_samples`), `keyness.py` (word-frequency deltas vs. `wordfreq`'s general-English
baseline), `structural.py` (sentence length, punctuation, CTA/question-opening rates,
etc.), `close_read.py` (qualitative LLM read â self-hosted Ollama only, per hard rules,
since her raw writing is sensitive), `build_profile.py` (merges all three + curated
few-shot examples into the single `voice_profile` row), `run.py` (CLI entrypoint:
`python -m wpa_content_engine.voice_engine.run`).

Smoke-tested end to end with `seed_demo_samples.py` (5 made-up placeholder posts, NOT
her real voice) â confirmed keyness/structural stats and the Ollama close-read all
visibly reflected the input rather than returning generic output. Demo data then wiped
via `clear_all_samples()`; both `voice_samples` and `voice_profile` are empty again.

**To finish this level**: feed in her real LinkedIn posts (15-20+ ideally) via
`ingestion.add_sample(text, source_type="linkedin_post")`, then rerun
`python -m wpa_content_engine.voice_engine.run`. Requires Ollama running locally with a
model pulled (`llama3.2` or `llama3` both present on this machine; model configurable
via `OLLAMA_MODEL` in `.env`).

Level 4: not started.
