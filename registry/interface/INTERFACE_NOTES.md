# Interface Notes

The `registry_widget.html` file is a self-contained, single-file HTML artifact. It runs in any browser with no dependencies, no build step, and no external requests.

## What it does

1. Renders the registry's seven entries as expandable rows
2. Filters by tier (audit / advisory / reference)
3. Sorts by name, cost, tokens, or status
4. Shows summary stats at the top (total count, in-production count, eval coverage, average cost)
5. Adapts to light and dark mode automatically based on system preference
6. Action buttons (View body, Run, Eval history) acknowledge the user click but do not currently send the action anywhere

## What it does not do

1. **No backing store.** Data is hardcoded in the `data` array inside the script tag. Refreshing or modifying entries means editing the HTML file by hand. To make this real, replace the `data` array with a `fetch()` from `INDEX.json` or from a database.

2. **No actual prompt execution.** The "Run" button shows an alert. Wiring it up requires a model API connection.

3. **No actual evaluation.** The "Eval history" button shows an alert. Wiring it up requires connecting to the eval data in `eval_batch_001_data.json` and rendering it.

4. **No prompt body display.** The "View body" button shows an alert. Wiring it up requires loading the markdown files in `prompts/` and rendering them — probably easiest with `marked.js` or similar.

5. **No version pinning controls.** Both v1.0.0 and v1.1.0 of consensus_protocol are visible, but there's no UI to mark one as the active default.

6. **No composition graph view.** The `composes` field is rendered as text but not visualized.

7. **No edit or add operations.** Read-only by design at v0.1.

## How to make it live (rough roadmap)

In rough order of value:

### Step 1: Connect the data layer

Replace the hardcoded `data` array with:

```javascript
const data = await fetch('../INDEX.json').then(r => r.json()).then(j => j.prompts);
```

If hosted statically (GitHub Pages, S3, Vercel static), this works immediately. If you want write access too, this is where you swap in a real database connection.

### Step 2: Wire up "View body"

Each prompt entry has a `file` field pointing to the markdown file. Wire the button to fetch and render that file:

```javascript
async function viewBody(d) {
  const response = await fetch('../' + d.file);
  const md = await response.text();
  // render with marked.js or similar
  document.getElementById('modal').innerHTML = marked.parse(md);
}
```

### Step 3: Wire up "Run"

This is where it gets real. The button needs to:

1. Open a directive input field
2. Take user-supplied text
3. Construct an API call to the prompt's default model with the prompt body + directive
4. Stream the response back into a result panel
5. Optionally save the run to eval history

The simplest scaffolding is calling the Anthropic / OpenAI / Google / xAI API directly. The most flexible is routing through an MCP layer that handles model selection.

### Step 4: Wire up "Eval history"

Each prompt has a list of associated eval batches. The button should open a panel showing:

- Eval batch ID and date
- Models tested
- Verdict distribution
- Cost summary
- Link to the full eval batch document

The data is in `eval_batch_001_data.json` — easy to load and render.

### Step 5: Add edit / publish / promote actions

This is where multi-user concerns become real:

- Who can publish a prompt (move from draft → production)?
- Who can promote a version (mark a new version as the active default)?
- How are edits tracked?
- How are eval runs attributed to authors?

These are not implementation problems; they're permission-system design problems. They probably need to be answered before the writeable UI ships.

### Step 6: Composition graph view

Once at least two prompts compose, render the dependency graph. D3 force-directed graph or similar. Each node is a prompt; each edge is a `composes` relationship. Click a node to focus it.

## Why a static HTML file at v0.1

A few reasons this version is deliberately simple:

1. **Zero deployment cost.** Open the file. It works.
2. **Inspectable.** Anyone can View Source and understand exactly what's happening.
3. **No premature framework.** A v0.1 registry with 7 entries doesn't need React, doesn't need Tailwind, doesn't need a build step. Adding those before they're needed is a tax that compounds.
4. **Honest about state.** Hardcoded data makes it obvious this is a snapshot, not a live system. That honesty is appropriate for v0.1.

## Browser compatibility

Tested mentally on modern Chrome, Safari, Firefox, Edge. Uses standard ES6+ features (template literals, arrow functions, optional chaining). No polyfills needed for any browser shipped after ~2021.

The dark-mode media query (`prefers-color-scheme: dark`) is widely supported. Users on systems without dark-mode preferences just see the light theme.

## Customization

Color palette, typography, and spacing are in CSS variables at the top of the `<style>` block. Change the variables to rebrand. The Lati Cooki / Clista typeface preferences (Fraunces / Geist) could be swapped in by replacing `--font-sans` and adding a Google Fonts import — but the current sans-stack matches claude.ai's native styling, which is intentional for the v0.1 snapshot.
