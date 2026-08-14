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

Level 4: not started.
