"""Renders a filled template to LinkedIn-ready files with headless Chromium (Playwright).

Single posts -> one PNG (1080x1350, or 1080x1080 for the announcement). Carousels -> a
PNG per slide plus one PDF with a page per slide, which is how LinkedIn takes carousels
(a "document" post). After rendering, each slide is measured for text that overflowed
its box, so a too-long line is caught rather than shipped cut off.

This is the one swappable piece: when PowerPoint templates arrive, a PowerPoint
renderer can sit behind the same render() call.
"""

import json
import pathlib
import threading
import uuid

import jinja2

ENGINE_DIR = pathlib.Path(__file__).resolve().parent
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(ENGINE_DIR / "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><base href="{base}">
<link rel="stylesheet" href="fonts.css">
<style>
  html,body{{margin:0;padding:0;background:#fff;-webkit-font-smoothing:antialiased}}
  *{{box-sizing:border-box}}
  @page{{size:1080px {height}px;margin:0}}
  .slide{{break-after:page}}
</style></head><body>{body}</body></html>"""

# Any element whose content is taller/wider than its box means text didn't fit.
_OVERFLOW_JS = """() => {
  const out = [];
  document.querySelectorAll('.slide').forEach((slide, i) => {
    const sr = slide.getBoundingClientRect();
    for (const el of slide.querySelectorAll('*')) {
      if (el.tagName === 'IMG') continue;
      // Giant display glyphs (the quote mark, "6h -> 40m", step numerals) overhang their
      // line box by design - only body/headline-size text can genuinely overflow.
      let display = false;
      for (let a = el; a && a !== slide; a = a.parentElement) {
        if (parseFloat(getComputedStyle(a).fontSize) >= 150) { display = true; break; }
      }
      if (display) continue;
      const r = el.getBoundingClientRect();
      // 6px tolerance: wide letter-spacing on the mono labels adds ~3px after the last letter
      const tooTall = el.scrollHeight > el.clientHeight + 6 && el.clientHeight > 0;
      const tooWide = el.scrollWidth > el.clientWidth + 6 && el.clientWidth > 0;
      const outside = r.bottom > sr.bottom - 79 || r.right > sr.right - 79;
      if (tooTall || tooWide || (outside && el.textContent.trim())) {
        out.push({slide: i + 1, text: el.textContent.trim().slice(0, 60)});
        break;
      }
    }
  });
  return out;
}"""


class RenderResult(dict):
    """{"pngs": [paths], "pdf": path or "", "overflow": [{"slide", "text"}]}"""


def _render_in_thread(fn):
    """Playwright's sync API refuses to run inside an asyncio loop - which is exactly
    where the dashboard's background events run. A plain thread has no loop."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def render(template_key: str, slots: dict, out_dir: pathlib.Path, photo: str = "", height: int = 1350) -> RenderResult:
    from playwright.sync_api import sync_playwright

    out_dir = pathlib.Path(out_dir).resolve()  # file URIs need an absolute path (the upload dir is relative)
    body = _env.get_template(f"{template_key}.html.j2").render(s=_ns(slots), photo=_file_url(photo) if photo else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:6]  # fresh names each render, so browsers never show a stale cached image
    html_path = out_dir / f"_render-{token}.html"
    html_path.write_text(_PAGE.format(base=ENGINE_DIR.as_uri() + "/", height=height, body=body), encoding="utf-8")

    def work():
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": height}, device_scale_factor=1)
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            overflow = page.evaluate(_OVERFLOW_JS)
            pngs = []
            for i, slide in enumerate(page.locator(".slide").all(), start=1):
                path = out_dir / f"slide-{i}-{token}.png"
                slide.screenshot(path=str(path))
                pngs.append(str(path))
            pdf = ""
            if len(pngs) > 1:
                pdf = str(out_dir / f"carousel-{token}.pdf")
                page.pdf(path=pdf, width="1080px", height=f"{height}px", print_background=True)
            browser.close()
            return RenderResult(pngs=pngs, pdf=pdf, overflow=overflow)

    try:
        return _render_in_thread(work)
    finally:
        html_path.unlink(missing_ok=True)


def _file_url(path: str) -> str:
    return pathlib.Path(path).resolve().as_uri()


class _NS:
    """Lets templates write s.label for dict keys (and nested dicts/lists). A plain
    object, not a dict subclass - otherwise s.items would be dict.items, not the field."""

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name):
        return self._data.get(name)


def _ns(value):
    if isinstance(value, dict):
        return _NS({k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(v) for v in value]
    return value


if __name__ == "__main__":  # quick manual check: python -m ...visuals_engine.render <key> '<json>'
    import sys

    res = render(sys.argv[1], json.loads(sys.argv[2]), pathlib.Path("visual-test"))
    print(res)
