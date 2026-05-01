# Review-Feedback Pipeline Design

**Date:** 2026-05-02
**Status:** Draft

## Problem

The Plan tab splits configuration/instruction input (top) from the action preview (middle) and execution controls (bottom). After reviewing actions, users must scroll back up to write feedback in the textarea, then find the Revise button — context is lost.

## Goal

Restructure the Plan tab into a linear pipeline: **Configure → Review → Feedback → Revise/Execute**. Add three levels of collapsible feedback (per-action, per-category, global) so users can give targeted instructions directly where they see the actions.

## Layout

```
Panel A  [Configure]      focus / max-actions / timeout + [Generate]
Panel B  [Stats]          总计 可执行 待审查 错误 警告
Panel C  [Action Preview] categories with collapsible feedback inputs
Panel D  [Feedback+Ops]   textarea + [Revise] [Execute] [Download Report]
Panel E  [File Import]    <input type="file">
```

Top panel shrinks to configuration only. The textarea moves from top to Panel D (below the preview), alongside Revise and Execute buttons.

## Three-Level Feedback

### Per-action

- Trigger: click 💬 icon on any action row
- UI: inline `<input>` expands below the action row
- Collected on: Revise click
- Icon state: filled when content present

### Per-category

- Trigger: click 💬 icon on any category header
- UI: inline `<input>` expands below the category header, above action list
- Collected on: Revise click
- Icon state: filled when content present

### Global

- Trigger: textarea in Panel D, always visible
- UI: standard `<textarea>`, same as current but relocated
- Collected on: Revise click

## Feedback Assembly

When Revise is clicked, `collectAllFeedback()` gathers all non-empty inputs and builds a structured string:

```
User instruction: {global textarea content}

Per-category feedback:
- /编程: 这组偏激进
- 需要审查: 先别动

Per-action feedback:
- move "React" → /编程: 放前端子文件夹
- review "Bookmark X": 工作相关，别删
```

Empty levels are omitted. This string is passed as `userInstruction` to the existing revise background job. No changes needed in `ai_planner.js` or `service_worker.js`.

## Button States

- **Generate**: enabled when API is configured (unchanged)
- **Revise**: enabled when a plan is loaded AND at least one feedback input has content
- **Execute**: enabled when plan passes lint with executable actions (unchanged)

## HTML Structure Changes

**Panel A** — remove textarea and Revise button, keep only:
```html
<div class="panel">
  <strong>Generate organization plan</strong>
  <div class="row"> focus-path | max-actions </div>
  <button id="generate-ai-btn">Generate AI Plan</button>
</div>
```

**Panel C** — `buildCategoryElement` adds:
- 💬 icon button in category header (right side, before badge)
- Collapsible `<input class="feedback-input">` below header
- Each `buildActionItem` adds a 💬 icon and collapsible `<input>`

**Panel D** — new panel combining textarea + action buttons:
```html
<div class="panel">
  <label>Organization notes</label>
  <textarea id="user-instruction" rows="2"></textarea>
  <div class="button-row">
    <button id="revise-ai-btn">Revise</button>
    <button id="execute-btn">Execute</button>
  </div>
  <button id="download-report-btn">Download Report</button>
</div>
```

**Panel E** — file import moved to a thin separate panel at the bottom.

## CSS Additions

```css
.feedback-toggle {
  cursor: pointer;
  opacity: 0.5;
  font-size: 12px;
}
.feedback-toggle.has-content {
  opacity: 1;
}
.feedback-input {
  display: none;
  margin: 4px 0;
}
.feedback-input.open {
  display: block;
}
```

## Files Modified

| File | Change |
|------|--------|
| `extension/popup.html` | Reorder panels, move textarea to Panel D, add Panel E for file import |
| `extension/popup.js` | Add `collectAllFeedback()`, modify `buildCategoryElement`/`buildActionItem` for 💬 toggle + input, update Revise handler to use collected feedback, move Revise button enable/disable logic |
| `extension/popup.html` `<style>` | Add `.feedback-toggle`, `.feedback-input` styles |

## Files NOT Modified

- `ai_planner.js` — feedback is assembled as text, passed through existing `userInstruction` path
- `service_worker.js` — no changes, same revise message format
- `storage_helpers.js` — no changes
- `plan_lint.js` — no changes

## Verification

1. Generate a plan — confirm Panel C shows categories with 💬 icons
2. Click a 💬 on an action — confirm inline input appears
3. Type feedback in per-action, per-category, and global inputs
4. Click Revise — confirm feedback is assembled and sent
5. Execute — confirm plan executes normally
6. Reload popup — confirm plan restores, feedback inputs clear (feedback is ephemeral)
7. Run `python -m pytest tests/ -v` — all existing tests pass
