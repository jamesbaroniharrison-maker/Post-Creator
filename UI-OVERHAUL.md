# UI Overhaul — instructions for Claude Code

Reference mockup: `design-reference.html` in this repo — open it before starting, it shows the target colours, buttons, empty state, and full Home page rendered. Everything below assumes that reference. Work in this order: design tokens first, shared components second, then each page. Don't touch page-specific layout until the shared components exist — every page reuses them.

## 1. Design tokens (do this first, everywhere)

Replace all current colour values with:

| Token | Hex | Used for |
|---|---|---|
| `bg` | `#14110F` | page background |
| `surface` | `#1C1815` | card background |
| `surface-2` | `#221D19` | input backgrounds |
| `border` | `#2E2822` | default borders |
| `border-strong` | `#3D362E` | hover borders, input borders |
| `text` | `#F2EDE4` | primary text |
| `text-muted` | `#8C8479` | labels, secondary text |
| `gold` | `#C9A66B` | data only — stat numbers, active nav underline, focus rings |
| `terracotta` | `#BF6E4E` | actions only — primary buttons, hover `#A85D3F` |

Two accents, two jobs, never swap them: gold shows information, terracotta triggers an action. If a stat number is currently rose/terracotta, change it to gold. If a button is currently gold/tan, change it to terracotta.

Type: keep serif (current stack) for the app title, page titles (`h2`, e.g. "Stats", "Review", "Accepted"), and empty-state headings only. Everything else — labels, buttons, body text, nav — system sans.

Spacing: 8px base unit. Card padding 24px (40px for the main content card on Home). Gap between sibling cards 14-16px. Gap between major sections 40px.

Radius: 12px on cards, 8px on buttons and inputs.

## 2. Shared components (build once, use everywhere)

**Top nav** — currently a filled box on the active tab. Replace with: no background at all, `text-muted` colour on inactive tabs, `text` colour + a 2px `terracotta` underline (14px padding below the label) on the active tab. Add a full-width 1px `border` line under the whole nav row.

**EmptyState component** — build this once and use it on every page that currently just shows bare gray text (Review, Rejected, Topic Bank, Past Weeks all have this problem right now). Centered, max-width 380px, dashed `border-strong` outline, 12px radius, 48px vertical / 32px horizontal padding, a single muted icon at 32px, a serif heading, one line of `text-muted` body copy below it. Per page:
- Review, currently "Nothing waiting for review right now." — icon: inbox. Heading: "All caught up". Body: "Nothing's waiting for review right now — new drafts will show up here."
- Rejected, currently "Nothing rejected right now." — icon: trash/x-circle. Heading: "Clean record". Body: "Nothing's been rejected — rejected drafts will land here with a reason attached."
- Topic Bank, currently "Nothing banked right now." — icon: archive. Heading: "Bank's empty". Body: "Research findings that don't get used straight away will collect here."
- Past Weeks, currently "No history yet." — icon: calendar. Heading: "No history yet". Body: "Once a week's posts are through, they'll show up here."

Keep each page's existing helper line above the empty state (e.g. "Only the most recent 5 are kept — older ones are deleted automatically") — just restyle it: `text-muted`, 13px, with 16px of space below it before the empty-state card, so it clearly reads as a persistent page note rather than competing with the empty state itself.

**Buttons** — one primary (filled `terracotta`, white text, 600 weight) per section, everything else outline (`border-strong` border, `text` colour, transparent fill). Never two filled buttons next to each other — if a screen currently has that, downgrade the less important one to outline.

**Form fields** — every input needs a real `label` element above it, 12px, `text-muted`, 6px margin below. Placeholder text stays, but shortens to just the example (e.g. label "Topic", placeholder "e.g. the latest AI model release" — not both crammed into the placeholder like today).

## 3. Home page

- Stats: split into two visually distinct groups, not one row of seven. Group 1 (Drafted / Approved / Published / Rejected): solid `surface` cards, as now. Group 2 (Acceptance Rate / Avg Time to Review / Avg Time to Publish): same layout but dashed `border` outline and transparent fill, so it reads as "derived from the numbers above" rather than a fifth-through-seventh stat of equal weight. Add a small `text-muted` label ("This week's activity") above group 1.
- Weekly input: currently two separate flows (textarea + "Draft from note" button, and a separate dropzone + "Upload & draft" button) — merge into one. Single labeled section ("Note or upload"), textarea on top, dropzone directly below it, one button underneath both ("Draft this post") that works whichever one has content. Give the post-type dropdown its own label ("Post type") above it rather than showing the raw value with no heading.

## 4. Review / Rejected / Topic Bank / Past Weeks

Apply the EmptyState component from §2. No other layout changes needed on these until they have real content to display — don't design a populated state you haven't seen data in yet.

## 5. Accepted page

- The week-selector row ("This week / Next week / In 2 weeks / In 3 weeks") and the status-filter row ("All / Accepted, not published / Published") currently use the same button style, so all seven read as one confusing row. Keep week-selector as filled pill buttons. Change the status filter to a single bordered segmented control — one container, no gaps between the three options, smaller than the week pills — so it's visually obvious these are two different kinds of filter.
- Day cards: give the current day a 2px `terracotta` border instead of `border`, so it's identifiable at a glance in the 7-card grid without reading every "Today" label.
- Add a small "Notes" label above each day's textarea, separate from the "Pencil in what this day should be about…" placeholder.
- Tighten the dropdown + "Save note" row at the bottom of each card: dropdown flexes to fill available space, button stays fixed-width, small gap between them — currently both are full width and cramped.

## 6. Settings page

- "Generate a post now" / "Run research now" / "Force next search topics" currently share one card with whitespace-only separation, and end up visually unbalanced because they have different numbers of fields. Split into three separate cards in a row, each full height regardless of content, 14px gap between them.
- Every input on this page needs the real-label treatment from §2 — "Topic - e.g. the latest AI model release", "Topic to search for", and "your email address" are all currently placeholder-only.
- Email Reminders: add a vertical divider (1px `border`) between "Personal story reminder" and "Weekly post digest", or put each in its own small card — right now they read as one continuous form rather than two independent settings.
- The "Save" button is currently undersized relative to the form above it — match it to the primary button size used elsewhere (e.g. "Research + draft" on Home).
