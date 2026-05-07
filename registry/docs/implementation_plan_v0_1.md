# Build Prompt Registry Web Interface

We will add a lightweight Node.js backend to make the existing `registry_widget.html` functional. This honors the philosophy established in `INTERFACE_NOTES.md` by avoiding heavy frameworks. 

## The Objective
The focus of **v0.1** is to explicitly **test the "bucket" workflow** using flat JSON files. This will validate if the manual copy/paste eval loop is viable before we invest in the **v0.2** database migration.

---

## v0.1 Proposed Changes (Testing the Bucket)

### Setup Minimal Backend
- **`package.json`**: Initialize a basic npm project with `express`.
- **`server.js`**: Create a lightweight Express server that:
  - Serves static files from the `interface`, `prompts`, and `evals` directories.
  - `GET /api/prompts`: Read `INDEX.json`.
  - `POST /api/prompts`: Create a new prompt (generates `.md` file, appends to `INDEX.json`).
  - `GET /api/prompt-body`: Read prompt body from `.md` file.
  - `POST /api/evals`: Accept a manually pasted LLM output, save it to `evals/eval_batch_001_data.json` (the bucket), and update the prompt's `eval_status` in `INDEX.json`.

### Extend Vanilla Interface
- **`interface/registry_widget.html`**:
  - **Data Layer**: Fetch live data from `/api/prompts`.
  - **Add Prompt**: Modal form to capture schema requirements.
  - **Test the Eval Loop (Two-Way Workflow)**: 
    1. Modal gives you the fully compiled prompt to **Copy**.
    2. You run it externally.
    3. You **Paste** the LLM's response back into a "Results" textarea.
    4. You manually assign grades/metrics and hit save to feed the eval bucket.

---

## v0.2 Roadmap (The Relational Eval Engine)

Once v0.1 proves the manual loop, the architecture hits the limits of flat JSON files. v0.2 will upgrade the registry from a storage bucket to an active eval engine:

### 1. Database Migration (SQLite)
Replace `INDEX.json` and `eval_batch_data.json` with a local SQLite database. This solves the highly relational nature of the data (Prompts → Versions → Eval Batches → Runs → Metrics) while maintaining local portability.

### 2. Auto-Grading (Meta-Prompts)
Replace manual metric checkboxes with LLM-assisted grading. We will register an "Eval Analysis Prompt". When a user runs a batch of models, this utility prompt will ingest all outputs, test them against the prompt's `expected_signals`, and output structured grading JSON.

### 3. Human-in-the-loop Approval UI
Update the "Save Eval" UI from a blank input form into a "Review & Approve" screen. The system will present the auto-graded metrics for the batch, allowing the human to override any hallucinated grades before committing to the SQLite database.

---

## Verification Plan (For v0.1)
- Run `node server.js` and test API routes via `curl`.
- Open `http://localhost:3000`.
- Submit a new prompt via the "Add Prompt" modal, verify `.md` generation.
- Click "Run" on a prompt, compile it, copy it, paste dummy text back into the Results box, and verify it successfully feeds the flat-file eval bucket.
