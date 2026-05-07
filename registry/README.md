# Prompt Registry — v0.1

Generated from a single conversation between Troy (`troy_builds`) and Claude Opus 4.7 on 2026-05-04.

This archive contains the complete artifact set produced during the session that defined the prompt-as-application thesis, built and stress-tested Consensus Protocol v1.0.0, ran a four-model eval batch on a real directive, identified a foundational defect in v1.0.0, specified v1.1.0 to fix it, and rendered an interactive registry interface.

The ordering of files mirrors the ordering of insight: prompts first (the core asset), then evals (what tested them), then docs (what was learned), then interface (how to use it).

## What's in this archive

```
registry/
├── README.md                              # This file
├── INDEX.json                             # Machine-readable index of all entries
│
├── prompts/
│   ├── consensus_protocol_v1_0_0.md      # The validated prior version
│   ├── consensus_protocol_v1_1_0.md      # The draft current version
│   ├── consensus_protocol_changelog.md   # Why v1.1.0 exists
│   └── prompt_schema.md                  # Schema for any registered prompt
│
├── evals/
│   ├── eval_batch_001.md                 # Four-model run on StrategiAI directive
│   ├── eval_batch_001_data.json          # Structured comparison data
│   └── strategiai_directive.md           # The directive itself, preserved
│
├── docs/
│   ├── session_findings.md               # The seven substantive findings
│   ├── prompt_as_application.md          # The reframe that started it all
│   ├── registry_design_notes.md          # Schema decisions and open questions
│   └── session_transcript_notes.md       # What this session is (and isn't)
│
└── interface/
    ├── registry_widget.html              # The interactive registry UI
    └── INTERFACE_NOTES.md                # What the widget does and doesn't do
```

## How to use this archive

**If you want to use Consensus Protocol on a real decision:**
Read `prompts/consensus_protocol_v1_1_0.md`. Pick a model from the recommendation hierarchy in `evals/eval_batch_001.md`. Paste the prompt body, append your directive, run.

**If you want to extend the registry:**
Read `prompts/prompt_schema.md` and `docs/registry_design_notes.md`. The schema is opinionated about what fields a registered prompt needs; the design notes explain why.

**If you want to understand the methodology:**
Read `docs/prompt_as_application.md` and `docs/session_findings.md` in that order. Then look at the eval batch for an example of multi-model evaluation in practice.

**If you want to deploy the interface:**
Open `interface/registry_widget.html` in any browser. It's a single-file HTML artifact with no dependencies. The widget has no backing store yet; see `interface/INTERFACE_NOTES.md` for what's missing.

## Known limitations

This is v0.1. Honest gaps:

1. **No persistence layer.** The widget renders entries from a hardcoded array. To make this real, the data needs a backing store (JSON file, Notion DB, Postgres, anything).
2. **Three of seven prompts are not yet eval-validated.** `lite_fast_review` is unevaluated; `industry_playbook_technology` is reference-tier and untested as a composable; the v1.1.0 regression test for `consensus_protocol` is pending.
3. **No composition graph yet.** The `composes` field exists on every entry but is empty across the board. The first composition use case (consensus_protocol + citation_verifier) is specified in design notes but not built.
4. **Quality cliff is unprobed.** All four eval-batch runs were on frontier-class models. We don't yet know whether mid-tier models (Sonnet 4.6, GPT-5.4 mini, Gemini 2.5 Flash) can execute Consensus Protocol at acceptable quality.

These are the four highest-priority next-build items.

## Provenance

- Authored: 2026-05-04
- Author: troy_builds
- Co-authored with: claude-opus-4.7
- Eval data sourced from: this conversation's four-model comparison (Claude Opus 4.7, Grok 4.3, GPT-5.5, Gemini 2.5 Pro)
- Owner entity: Lati Cooki LLC (per session context)
