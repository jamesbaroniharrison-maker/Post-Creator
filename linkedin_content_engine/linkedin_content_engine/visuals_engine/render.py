"""Renders a filled template to LinkedIn-ready files with headless Chromium (Playwright).

Single posts -> one PNG (1080x1350, or 1080x1080 for the announcement). Carousels -> a
PNG per slide plus one PDF with a page per slide, which is how LinkedIn takes carousels
(a "document" post). After rendering, each slide is measured for text that overflowed
its box, so a too-long line is caught rather than shipped cut off.

The designs are the Claude Design HTML files in designs/ (see designs.py), filled
and rendered exactly as delivered.
"""

import json
import pathlib
import threading
import uuid

ENGINE_DIR = pathlib.Path(__file__).resolve().parent

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><base href="{base}">
<link rel="stylesheet" href="{fonts}">
<style>{design_css}

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
      if (el.tagName === 'IMG' || el.closest('[data-decor]')) continue;
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
      // Pushed past the slide's own edge (slides clip with overflow:hidden). Not the 80px
      // margin: several designs run bands and panels to the edge on purpose.
      const outside = r.bottom > sr.bottom + 1 || r.right > sr.right + 1;
      // A box only loses text if it clips (overflow not visible) or holds the text itself -
      // layout boxes with decorative overhang (photo corner marks, the timeline line)
      // overflow harmlessly.
      const cs = getComputedStyle(el);
      const clips = cs.overflowX !== 'visible' || cs.overflowY !== 'visible';
      const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (((tooTall || tooWide) && (clips || ownText)) || (outside && el.textContent.trim())) {
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
    from linkedin_content_engine.visuals_engine.designs import DESIGNS_DIR, load_designs

    design = load_designs()[template_key]
    body = design.fill(slots, photo_url=_file_url(photo) if photo else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:6]  # fresh names each render, so browsers never show a stale cached image
    html_path = out_dir / f"_render-{token}.html"
    page_html = _PAGE.format(
        base=DESIGNS_DIR.as_uri() + "/",  # the designs' own assets/logos/ paths resolve from here
        fonts=(ENGINE_DIR / "fonts.css").as_uri(),
        design_css=design.css,
        height=height,
        body=body,
    )
    html_path.write_text(page_html, encoding="utf-8")

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


if __name__ == "__main__":  # quick manual check: python -m ...visuals_engine.render <key> '<json>'
    import sys

    res = render(sys.argv[1], json.loads(sys.argv[2]), pathlib.Path("visual-test"))
    print(res)
