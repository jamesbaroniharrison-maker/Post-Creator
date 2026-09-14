# Personal LinkedIn Content Engine — Improvement History

A handoff document summarizing everything built since this project was repurposed
from a client (WPA) content engine into James's own personal LinkedIn content system
(2 Sept 2026 → 14 Sept 2026). Written for someone who doesn't have the full build
history in front of them, so they can pick up where this left off and suggest what to
improve next — particularly around the voice-matching / corpus system, which is the
part still most gated by data rather than engineering.

The short version: this is not a fine-tuned or trained model. It's a Python app that
calls an off-the-shelf LLM (Ollama `llama3` locally, or Gemini) through a prompt, and
everything described below is prompt-engineering, retrieval, and statistics wrapped
around that call — real, well-understood techniques (Burrows' Delta, Zeta, PMI,
embedding retrieval, POS-tagging), not machine-learning training. There is no GPU
fine-tuning pipeline, no base-model weight adaptation, and no training dataset in the
ML sense. Anyone advising on "how to improve the model" should know that constraint
up front: the lever available here is data (the voice corpus) and how it's used at
inference time, not weights.

---

## 1. What the system does, end to end

1. **Research**: a daily cron pulls AI/tech/market news from a trusted-domain list
   (Tavily search + Gemini scoring), stores findings in a "topic bank" tiered
   high/mid/low.
2. **Drafting**: for a chosen topic (from the bank, or a personal note/reflection),
   an LLM drafts a LinkedIn post using a CPIO (Convey/Package/Information/Order)
   planning structure and THBM (Topic/Hook/Body/Media) execution levers — funnel
   stage, hook posture, length, structural format, and media pairing are all picked
   **deterministically in Python** (not left to the model), rotating so consecutive
   posts don't repeat the same combination.
3. **Voice matching**: every draft is scored and shaped against a real corpus of
   James's own writing (see below) so it sounds like him, not like a generic LLM
   voice.
4. **Review**: every draft lands in a dashboard for a human accept/redraft/reject
   decision — nothing publishes automatically.

## 2. The voice corpus — what it is and how it's built

The corpus is a table of real writing samples (`VoiceSample`), each tagged with a
`source_type`:

- `linkedin_post` — actual past LinkedIn posts, pasted in directly.
- `gemini_qa` — answers to interview-style questions James has answered in
  conversation with Gemini (a separate AI), pasted in either as single Q&A pairs or
  as a whole labeled transcript that gets parsed into multiple samples. These are
  treated as the *most* authentic material available — unscripted, first-person,
  James's own words with no editing for a LinkedIn audience — and are weighted
  higher in the statistics below (`SOURCE_AUTHENTICITY_WEIGHT = {"gemini_qa": 2.5}`).
- `audio_transcript` — voice notes transcribed to text via the capture pipeline.

**Current corpus size: 6 samples (2 `linkedin_post`, 4 `gemini_qa`).** This is the
single biggest constraint on everything below — several techniques are built and
working correctly but are explicitly gated on having more data before they can
produce fully stable results. More samples, especially more real LinkedIn posts
specifically (the `linkedin_post` register is the one actually being generated,
and it's the thinnest at only 2), is the highest-leverage thing anyone could add.

The dashboard's `/voice` page is the only way samples get added: paste a past post,
paste a single Gemini Q&A pair, or paste a whole labeled conversation transcript
(which gets parsed into a preview of separate Q&A pairs before anything is saved,
since the labeling convention is loose and worth a review step).

## 3. Voice-matching techniques, in the order they were built

All of this lives in `linkedin_content_engine/voice_engine/`.

### 3.1 Burrows' Delta — "does this sound like my usual writing?"

A real, long-established authorship-attribution statistic (Burrows, 2002). It scores
how far a candidate text's function-word frequency profile (the most common ~30
words in the corpus — "the," "i," "and," etc., deliberately including stopwords)
sits from the corpus's own normal range, z-scored per word and averaged. Lower =
closer to normal. Every draft gets scored and shown on the Review page as
"Voice match: close / typical / distant (raw score)".

### 3.2 Source-authenticity weighting

Both Delta and retrieval (below) weight `gemini_qa` samples 2.5x more heavily than
other sources when computing the corpus's "normal" statistics — because those
answers are considered the most authentic signal of how James actually talks.

**Honest finding from testing this**: weighting made Delta *noisier* at this corpus
size, not cleaner — the real cause was traced to sample-size/heterogeneity (mixing
2 short polished LinkedIn posts with several long raw transcripts makes any
per-word variance estimate unstable), not a bug in the weighting math itself. This
directly motivated the register-aware fix below.

### 3.3 Register-aware Delta

Splits the corpus by `source_type` and scores a draft against its own register's
baseline (LinkedIn posts specifically, since that's what's being generated) instead
of one pooled baseline mixing raw speech and polished posts together. This is the
real fix for the noise found in 3.2 — a real draft and a deliberately corporate
paragraph had scored within 0.01 of each other under the old pooled approach;
register-splitting is what actually addresses that, not just weighting harder.
Falls back to the old pooled score automatically until a register has enough of its
own samples (currently: `linkedin_post` only has 2, so it's "live" but not yet
validated — see 3.7).

### 3.4 Topic-similarity retrieval (few-shot examples)

Rather than showing the model a fixed set of example posts every time, the system
picks whichever real samples are most topically relevant to *this specific* draft
and shows 2 of those as few-shot examples — reducing the chance the model just
plagiarizes one example wholesale, while still anchoring tone/content to genuinely
similar real writing.

Two implementations exist:
- **Bag-of-words cosine similarity** (the original, always-available fallback).
- **Real local embeddings** via Ollama's `nomic-embed-text` model (274MB, fully
  local, free) — the literal implementation of "embedding-based retrieval," which
  a bag-of-words approach can only approximate. This is now the primary method,
  falling back to bag-of-words only if the embedding call fails for any reason.
  **A real bug was found and fixed here**: applying the same 2.5x authenticity
  weight to embedding similarity scores overrode genuine topical relevance (an
  unrelated story could outrank a genuinely on-topic one) — weighting was removed
  from this path specifically; it stays correct for Delta (which is about "what's
  normal for me") but wrong for retrieval (which is about "what's actually about
  this topic").
- **Embeddings are cached** on the `VoiceSample` row (computed once, reused) rather
  than recomputed on every single draft — cold cost ~20s for the whole corpus at 6
  samples, warm cost effectively zero.

### 3.5 Zeta words — "what do I reliably reach for, regardless of topic?"

Burrows'/Craig's Zeta: words that show up in most of the corpus's documents
(weighted by document presence, not raw frequency) — a different question from
Delta's "is the overall word mix normal." Even at only 6 samples this produced a
real, informative signature list ("have," "just," "really," "proud," "know" appear
across most documents) and is fed directly into the drafting prompt (a random
sample of 8 words per call, alongside a hand-authored vocabulary list).

### 3.6 Characteristic bigrams (PMI-ranked)

Two-word phrases that repeat across the corpus, ranked by Pointwise Mutual
Information against general-English word frequency (not just raw repeat count).
**This one had an honest false start**: raw-frequency ranking initially surfaced
only generic scaffolding ("i need," "i want," "you can") — not distinctive at all —
so it was shipped as diagnostic-only (visible on the Voice page, not fed into
drafting). PMI ranking later fixed this for real (surfacing genuinely distinctive
phrases like "useless busywork," "restarting fresh," "torrential rain"), at which
point it graduated into the drafting prompt directly. A real tokenizer bug (bare
apostrophes from quote-punctuation splitting became nonsense "words") was found and
fixed along the way.

### 3.7 Validation-split diagnostic

A genuine train/validation check on Delta itself: holds back a slice of real
samples per register, builds that register's baseline from everything else, and
checks whether the held-out real samples score "close" against it. If Delta is
working, real held-out writing should reliably come back close — if not, that's a
sign the metric needs revisiting, not just a data problem. Deliberately **not**
wired into live scoring (holding samples back would starve an already-tiny
baseline) — it's an on-demand calibration check, surfaced on the Voice page's
"Check corpus health" button. Currently reports "not enough data" for both
registers (needs ~7 samples per register with the current settings) — this is the
single clearest signal of what the corpus needs next.

### 3.8 Syntactic profile (spaCy)

Real POS-tagging and passive-voice detection via an actual dependency parse
(`en_core_web_sm`) — something regex genuinely cannot do. Currently diagnostic-only
(shown on the Voice page), deliberately **not** promoted into the drafting prompt.
Testing this before promoting it (the same discipline that caught the bigram false
start above) found the same register-heterogeneity problem as Delta: pooled
passive-voice rate is 6.2%, but splits to 18.2% (LinkedIn posts, n=2) vs 5.1%
(Gemini Q&A, n=4) — a 3x swing driven entirely by sample count, not a real
stylistic difference. Worth re-testing once there are more `linkedin_post`-register
samples specifically.

### 3.9 Best-of-N drafting with a quality floor

Rather than generating one draft and accepting whatever comes out, the system
drafts multiple independent full candidates for the same topic (default 3,
`DRAFT_BEST_OF_N` env var) and keeps whichever one scores lowest on register-aware
Delta. This is "spend more inference time instead of more engineering" — the most
direct lever available without training infrastructure.

Most recently improved with an actual **quality floor**: previously it just kept
the least-bad of a fixed batch of 3, even if all 3 still scored "distant." Now, if
the best candidate after one round still scores at or above the distant threshold
(1.6), it drafts a second full round before settling — capped at 2 rounds total so
it can't loop forever on a corpus too small to ever produce "close." A real test
run against the current corpus took 273 seconds and needed both rounds (every
candidate scored distant against the current thin `linkedin_post` register) before
settling on its best available option — real evidence the corpus size is the
active constraint, not the retry logic.

### 3.10 Corpus-health dashboard

A "Check corpus health" button on the Voice page (no longer script-only) shows,
per register: sample count, whether register-aware Delta is live yet, and whether
it's been validated against a real held-out sample (3.7). This is the fastest way
to see exactly what's still data-limited versus what's actually working.

## 4. What this means for "improving the model" going forward

Because there's no training step, "improving the model" here means one of two
things: **more/better corpus data**, or **smarter use of the existing data at
inference time**. Concretely, in priority order:

1. **More `linkedin_post`-register samples specifically.** This register has only 2
   samples and is the one every draft is actually being generated as and judged
   against. Register-aware Delta, the validation diagnostic, and (per 3.8)
   syntax-based directives are all blocked on this specifically — not on total
   corpus size, but on this one register's size. Real past LinkedIn posts pasted
   into `/voice` are the single highest-leverage input right now.
2. **More `gemini_qa` samples** (35 themed interview questions were drafted earlier
   in this project specifically to prompt more of this authentic, unscripted
   material) — helps Zeta, bigrams, and the pooled/fallback Delta baseline broadly.
3. Once the corpus is larger, several already-built-but-gated features activate
   automatically with no further code changes: register-aware Delta becomes fully
   reliable instead of falling back to pooled, the validation diagnostic starts
   reporting real calibration numbers instead of "not enough data," and the syntax
   profile becomes trustworthy enough to test promoting into the drafting prompt.
4. Anything resembling actual fine-tuning (LoRA adapters, DPO preference training,
   KL-divergence distribution matching against a reference model) was explicitly
   evaluated and ruled out for this project — it needs training infrastructure
   (GPU pipeline, base model weights, a preference dataset) that doesn't exist here
   and was never part of the design. If a future direction wants to go there for
   real, that's a different kind of system than this one (an inference-only app
   calling Ollama/Gemini's APIs), not an upgrade to it.

---

*Everything above has been tested against the real database and real API calls, not
just written and assumed to work — see `CLAUDE.md` in this repo for the full,
dated engineering log with exact verification steps, real bugs found and fixed
along the way, and file/function references for every item above.*
