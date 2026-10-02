"""Turns a drafted post into a brand visual: pick one of the existing templates, fill its
words from the post, render it.

One narrow LLM call does the choosing and filling (same "one job per call" pattern as the
audit gate and privacy check in draft.py). Everything it returns is then checked in
Python, not trusted: the template must be one offered, fields must fit the spec's word
and list limits, and every number on the visual must appear in the post or its source -
a visual never shows a figure the post didn't contain. A failed check gets one retry with
the problems spelled out; text that still overflows the slide after rendering gets one
"shorten it" retry, then ships with a note rather than silently cut off.
"""

import json
import pathlib
import re
import shutil

import pydantic

from linkedin_content_engine.drafting_engine.draft import _chat
from linkedin_content_engine.visuals_engine.render import render
from linkedin_content_engine.visuals_engine.spec import CATALOG, candidate_templates

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_EM_DASH_RE = re.compile(r"\s*—\s*")

_SYSTEM_PROMPT = """You turn a finished LinkedIn post into the words for ONE branded image. \
You do not design anything - the layouts already exist. You pick which layout suits the \
post, then fill its text fields.

Rules:
- Every word comes from the post's own message. Shorter and punchier than the post, but \
never a new claim, story, or opinion the post doesn't make.
- NEVER put a number on the image that isn't written in the post or source text below. \
If the post has no real figures, don't pick a layout that needs one.
- The "_gold" fields are the payoff: the last few words that land the point, shown in \
gold italics. The plain headline sets it up; the gold part finishes the sentence.
- Respect every word limit in the layout's shape. Fewer words is always better.
- British spelling. No em dashes. No hashtags, no emoji, no question marks.
- Labels are short category tags (e.g. POINT OF VIEW, FIELD NOTES), not sentences.
- Call-to-action buttons invite a reply or a follow (e.g. "Tell me your version", "Follow for the next build"), never a sales offer, booking, or link the post doesn't already mention.
- Leave optional fields out entirely when the post gives you nothing real for them.

Layouts you may choose from:
{options}

Respond with strict JSON only, no markdown fences:
{{"template": "<one of the layout keys above>", "slots": {{ ...that layout's fields... }}}}"""


class VisualError(RuntimeError):
    pass


def _norm_num(token: str) -> str:
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _clean(value):
    """Deterministic em-dash strip on every string (brand rule, same as draft text)."""
    if isinstance(value, str):
        return _EM_DASH_RE.sub(", ", value).strip()
    if isinstance(value, dict):
        # A null / "None" means "leave it out" - drop it so the template's default applies
        # (otherwise None renders as the literal word NONE on the slide).
        return {k: _clean(v) for k, v in value.items() if v is not None and str(v).strip().lower() not in ("none", "null", "")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def check_slots(template_key: str, slots: dict, source_text: str) -> list[str]:
    """Everything wrong with a filled template, as plain sentences the model can act on."""
    spec = CATALOG[template_key]
    problems: list[str] = []
    try:
        spec.model.model_validate(slots)
    except pydantic.ValidationError as exc:
        for err in exc.errors():
            problems.append(f"field {'.'.join(str(p) for p in err['loc'])}: {err['msg']}")
        return problems

    for field, limit in spec.word_limits.items():
        words = len(str(slots.get(field) or "").split())
        if words > limit:
            problems.append(f'"{field}" has {words} words, the limit is {limit} - shorten it.')
    for field, (lo, hi) in spec.list_lengths.items():
        n = len(slots.get(field) or [])
        if not lo <= n <= hi:
            want = f"exactly {lo}" if lo == hi else f"{lo}-{hi}"
            problems.append(f'"{field}" has {n} items, it needs {want}.')

    allowed = {_norm_num(t) for t in _NUMBER_RE.findall(source_text)}
    invented = sorted({t for s in _strings(slots) for t in _NUMBER_RE.findall(s) if _norm_num(t) not in allowed})
    if invented:
        problems.append(
            f"these numbers are not in the post or source: {', '.join(invented)}. Remove them "
            "(or pick a layout that doesn't need a figure)."
        )
    return problems


def _ask(candidates: list[str], post_text: str, source_text: str, extra: str = "") -> dict:
    options = "\n".join(
        f'- "{k}" ({CATALOG[k].name}): {CATALOG[k].when}\n  Shape: {CATALOG[k].shape}' for k in candidates
    )
    user = f"Post:\n{post_text}\n\nSource text (the only other place numbers may come from):\n{source_text or '(none)'}"
    if extra:
        user += f"\n\n{extra}"
    content = _FENCE_RE.sub("", _chat(_SYSTEM_PROMPT.format(options=options), user).strip())
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("slots"), dict):
        raise VisualError("model returned no slots")
    return data


def _fill(candidates: list[str], post_text: str, source_text: str, extra: str = "") -> tuple[str, dict, list[str]]:
    """Ask, check, and on failure ask once more with the problems listed."""
    problems: list[str] = []
    key, slots = candidates[0], {}
    for attempt in range(2):
        note = extra
        if problems:
            note = (extra + "\n\n" if extra else "") + (
                f'Your last answer (layout "{key}") had these problems - fix every one:\n- ' + "\n- ".join(problems)
            )
        try:
            data = _ask(candidates, post_text, source_text, note)
        except (json.JSONDecodeError, VisualError) as exc:
            problems = [f"the response wasn't valid JSON with a slots object ({exc})"]
            continue
        key = data.get("template") if data.get("template") in candidates else candidates[0]
        slots = _clean(data["slots"])
        problems = check_slots(key, slots, source_text)
        if not problems:
            # Normalised through the spec model, so every optional field has its default.
            return key, CATALOG[key].model.model_validate(slots).model_dump(), []
    return key, slots, problems


def make_visual(
    post_text: str,
    source_text: str,
    media_pairing: str | None,
    out_dir: pathlib.Path,
    photo: str = "",
    template_key: str | None = None,
) -> dict:
    """Fill and render one visual for a post.

    Returns {"template", "slots", "pngs", "pdf", "note"}. `template_key` forces a layout
    (the dashboard's template switcher); otherwise the model picks from the layouts that
    suit the post's media pairing. Raises VisualError only if nothing usable came back.
    """
    has_photo = bool(photo) and pathlib.Path(photo).exists()
    if template_key:
        candidates = [template_key]
    else:
        candidates = candidate_templates(media_pairing, has_photo)
    source_all = f"{post_text}\n{source_text}"

    key, slots, problems = _fill(candidates, post_text, source_all)
    if problems and candidates != ["statement"] and not template_key:
        # Fall back to the simplest layout before giving up - one headline, nothing to count.
        key, slots, problems = _fill(["statement"], post_text, source_all)
    if problems:
        raise VisualError("; ".join(problems))

    spec = CATALOG[key]
    if out_dir.exists():
        shutil.rmtree(out_dir)  # one visual per post - a re-make replaces the old files

    def _render(s: dict):
        return render(key, s, out_dir, photo=photo if spec.needs_photo else "", height=spec.height)

    result = _render(slots)
    note = ""
    if result["overflow"]:
        too_long = "; ".join(f'slide {o["slide"]}: "{o["text"]}"' for o in result["overflow"])
        shorter = (
            f"Keep the layout \"{key}\" and the same message, but this text didn't fit on the "
            f"image - make it noticeably shorter: {too_long}"
        )
        key2, slots2, problems2 = _fill([key], post_text, source_all, shorter)
        if not problems2:
            retry = _render(slots2)  # fresh file names, so both sets sit side by side for now
            keep, drop = (retry, result) if len(retry["overflow"]) < len(result["overflow"]) else (result, retry)
            for f in [*drop["pngs"], drop["pdf"]]:
                if f:
                    pathlib.Path(f).unlink(missing_ok=True)
            if keep is retry:
                result, slots = retry, slots2
        if result["overflow"]:
            note = "Some text may not fit on the image - check it, or edit the slide text and re-make it."

    return {"template": key, "slots": slots, "pngs": result["pngs"], "pdf": result["pdf"], "note": note}
