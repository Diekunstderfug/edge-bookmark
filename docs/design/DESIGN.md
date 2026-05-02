# Edge Bookmark Advisor — Popup Design System

Date: 2026-05-02
Status: Approved

---

## Visual Thesis

A compact operations console made of ink, ruled lines, and terminal-grade controls: calm, dense, exact, and built like something you trust before letting it touch 1,000 bookmarks.

---

## Typography

```css
--font-ui: "IBM Plex Sans Condensed", "Aptos Narrow", sans-serif;
--font-mono: "IBM Plex Mono", "Cascadia Mono", monospace;
```

### Hierarchy

| Token            | Font           | Size | Weight | Line | Usage                          |
|------------------|----------------|------|--------|------|--------------------------------|
| popup-title      | font-ui        | 18px | 600    | 22px | Header project name            |
| tab-label        | font-ui        | 12px | 600    | 16px | Tab labels, uppercase          |
| section-title    | font-ui        | 13px | 600    | 18px | Pipeline phase titles          |
| body             | font-ui        | 13px | 400    | 18px | Prose, descriptions            |
| control-label    | font-ui        | 12px | 500    | 16px | Form labels                    |
| small            | font-ui        | 11px | 400    | 15px | Hints, meta text               |
| mono             | font-mono      | 11px | 400    | 15px | Paths, IDs, timestamps         |
| metric-value     | font-mono      | 20px | 600    | 24px | Stat numbers                   |
| action-row       | font-mono      | 12px | 400    | 16px | Preview action rows            |
| button           | font-ui        | 12px | 600    | 16px | Buttons                        |

Monospace carries the entire UI. Sans-condensed is reserved for titles and section headers only. This inverted convention creates the instrument-panel feel.

---

## Color System

Dark theme. Matte surfaces, sharp dividers, restrained accent. No gradients. No pastel.

```css
:root {
  /* Surfaces — luminance steps, not borders */
  --bg: #0f1115;
  --surface: #161922;
  --surface-raised: #1d212b;

  /* Text */
  --text: #e7e9ee;
  --text-muted: #9aa3b2;
  --text-faint: #6f7887;

  /* Accent — amber, used for state/progress/irreversible only */
  --accent: #d6b35a;
  --accent-strong: #f0c95c;
  --accent-muted: #6d5b2d;

  /* Borders — used sparingly, luminance contrast preferred */
  --border: #2b303b;
  --border-strong: #3a414f;

  /* Inputs */
  --input-bg: #10131a;
  --input-border: #343b49;

  /* Semantic */
  --success: #68c184;
  --warning: #e3b45d;
  --danger: #e06c75;
  --info: #6aa6d8;

  /* Interaction */
  --focus: #f0c95c;
  --disabled: #4d5564;
}
```

### Usage rules

- `--accent` only for: active tab indicator, progress state, irreversible operations. Never as decoration.
- Surface hierarchy: `--bg` → `--surface` → `--surface-raised`. Each step is 1 luminance tier up.
- `--border` is for inputs and structural rules only. Sections use luminance steps, not border lines.
- `--danger`: outline style only (transparent bg + colored border). Never filled red buttons.

---

## Layout

### Overall popup

```
width: 420px
max-height: 640px

┌─────────────────────────────────────┐
│ Header                              │  auto
├─────────────────────────────────────┤
│ Tabs (PLAN / LLM / PREFERENCES)     │  auto
├─────────────────────────────────────┤
│                                     │
│ Scrollable content                  │  1fr
│                                     │
├─────────────────────────────────────┤
│ Footer (operation bar)              │  auto
└─────────────────────────────────────┘
```

```css
body {
  width: 420px;
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-mono);
}

.popup {
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  max-height: 640px;
}
```

### Header

Left-aligned command surface. No centered title. No logo.

```
EDGE BOOKMARK ADVISOR
job: 2026-05-01-main        backend: extension
```

```css
.popup-title {
  font: 600 18px/22px var(--font-ui);
  letter-spacing: 0.02em;
}

.header-meta {
  font: 400 11px/15px var(--font-mono);
  color: var(--text-muted);
}
```

### Tabs

Uppercase, full-width, equal columns. Active tab: accent bottom border. Not pill buttons.

```
PLAN            LLM SETTINGS            PREFERENCES
━━━━━━━━
```

```css
.tab-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-bottom: 1px solid var(--border);
}

.tab-label {
  font: 600 12px/16px var(--font-ui);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  text-align: center;
  padding: 8px 0;
  color: var(--text-muted);
  cursor: pointer;
}

.tab-label.active {
  color: var(--text);
  border-bottom: 2px solid var(--accent);
}
```

### Pipeline sections

Each section is a full-width ruled block. Not a card. No border-radius. No shadow.

```
01 Configure                         ready
─────────────────────────────────────────────
```

Section header format: `number + title` left-aligned, `state label` right-aligned.

```css
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 8px 0 4px;
  border-top: 1px solid var(--border);
}

.section-number {
  font: 600 11px/15px var(--font-mono);
  color: var(--text-faint);
}

.section-title {
  font: 600 13px/18px var(--font-ui);
}

.section-state {
  font: 400 11px/15px var(--font-mono);
  color: var(--text-muted);
}
```

Collapsible sections use text affordances (`+`, `-`), not icons:

```
01 Configure                         open -
02 Stats                             done +
```

---

## Pipeline Flow

### 01 Configure

Source select, mode select, rules, strictness toggles. Primary action: `GENERATE DRAFT PLAN`.

Controls:
- Selects: full width, 30px high, `var(--input-bg)` background
- Toggles: text label + small rectangular switch
- Inputs: mono text for paths and IDs
- Buttons: rectangular, 30px high, all caps only for destructive/final actions

```css
button {
  font: 600 12px/16px var(--font-ui);
  height: 30px;
  background: var(--surface-raised);
  color: var(--text);
  border: 1px solid var(--border);
  cursor: pointer;
}

button:hover {
  background: var(--border);
}

button.primary {
  background: var(--accent);
  color: var(--bg);
  border-color: var(--accent);
}
```

### 02 Stats

Compact metric strip. No cards. No grid of boxes.

```
bookmarks      folders      duplicates      loose
1,284          137          48              312
```

```css
.metric-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
  gap: 4px;
}

.metric-value {
  font: 600 20px/24px var(--font-mono);
  color: var(--text);
}

.metric-label {
  font: 400 10px/14px var(--font-ui);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}
```

Warnings inline:

```
! 48 duplicate URLs found
! 312 loose bookmarks eligible for planning
```

```css
.warning-inline {
  font: 400 11px/15px var(--font-mono);
  color: var(--warning);
}
```

### 03 Preview

Audit-log style action rows. Dense, ruled, mono-heavy.

```
MOVE      /Loose/GitHub Actions docs
          → /编程/DevOps/GitHub

CREATE    /生信和基因组学/Single-cell

RENAME    /AI tools
          → /AI/Tools
```

```css
.action-type {
  width: 54px;
  font: 600 11px/15px var(--font-mono);
  color: var(--accent);
}

.action-path {
  font: 400 12px/16px var(--font-mono);
  color: var(--text);
}

.action-target {
  font: 400 12px/16px var(--font-mono);
  color: var(--text-muted);
}
```

Filter tabs at top (text tabs, not chips):

```
All  Move  Create  Rename  Remove  Risk
```

Risk rows use semantic left border:

```css
.action-row.danger {
  border-left: 2px solid var(--danger);
  padding-left: 8px;
}
```

### 04 Feedback + Ops

Collapsed by default after clean plan. Expanded when review feedback exists.

```
04 Feedback + Ops                    optional

Targeted feedback
[ Keep AI research under /AI, not /编程. Do not move papers. ]

Ops
[ ] Re-plan only affected actions
[ ] Preserve existing folder names

APPLY FEEDBACK
```

Command log below:

```
13:42 feedback applied       18 actions changed
13:39 draft generated        model gpt-4.1
13:37 snapshot loaded        1,284 bookmarks
```

```css
.log-entry {
  font: 400 11px/15px var(--font-mono);
  color: var(--text-muted);
  padding: 2px 0;
}

.log-timestamp {
  color: var(--text-faint);
}
```

### 05 Import

Final execution with restraint.

```
05 Import                            blocked until reviewed

Reviewed plan
[ reviewed_plan.json ]

Execution
[ DRY RUN ]  [ EXECUTE PLAN ]

Last report
0 moved · 0 created · 0 renamed · 0 removed
```

`EXECUTE PLAN` is visually serious but does not shout:

```css
.button-danger {
  background: transparent;
  color: var(--danger);
  border: 1px solid var(--danger);
  height: 30px;
}

.button-danger:hover {
  background: rgba(224, 108, 117, 0.1);
}
```

---

## LLM Settings Tab

Dense settings form with clear separation.

```
Provider
[ OpenAI-compatible ]

Base URL
[ https://api.openai.com/v1 ]

Model
[ gpt-4.1 ]

API key
[ stored ·••••••••••••        CHANGE ]

Planning behavior
Temperature      [ 0.2 ]
Max actions      [ 200 ]

TEST CONNECTION
```

Connection result as one-line status:

```
✓ connected · 624 ms · responses API
```

---

## Preferences Tab

Policy, not personalization.

```
Guardrails
[ on ] Never move protected roots
[ on ] Require reviewed plan before execution
[ on ] Block destructive remove actions

Review defaults
[ on ] Expand risky actions
[ on ] Show domain in preview
[ off ] Auto-collapse completed phases

Runtime paths
Snapshot dir    [ data/snapshots ]
Plans dir       [ data/plans ]
Jobs dir        [ data/jobs ]
```

---

## Differentiation

1. **Ledger UI instead of bookmark UI**
   Most bookmark extensions look like mini file explorers. This one looks like a change-control ledger: numbered phases, audit rows, state labels, action diffs, execution reports. The emotional message: "nothing moves without traceability."

2. **Feedback as an operations phase, not a chat box**
   The AI interaction is not conversational. Targeted feedback is a structured re-planning control inside the pipeline. The user issues constraints to a planning system.

---

## Anti-Slop Rules

- No purple gradients
- No 3-column icon grids
- No centered primary layout
- No decorative blobs
- No rounded marketing cards
- No oversized hero title
- No empty whitespace pretending to be elegance
- No friendly mascot tone
- No "AI magic" language
- No icon-dependent controls

---

## Implementation Notes

- Pure HTML/CSS. No frameworks. No Tailwind.
- Fonts loaded via `<link>` from Google Fonts or bundled as web fonts.
- All CSS variables in `:root` on `<html>` or `<body>`.
- Popup.js continues to manage state — CSS only changes appearance, not behavior.
- i18n system (`data-i18n` attributes + `t()` function) unchanged.
- `plan_lint.js` and `service_worker.js` unchanged by this design.
