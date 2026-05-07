# Prompt Schema

What every registered prompt needs. This schema was derived backward from Consensus Protocol — the type specimen — rather than designed forward as an abstract spec. Every field below maps to something an actual working prompt either has or measurably needs.

## Required fields

```yaml
id:               string         # snake_case identifier, no version
version:          semver         # 1.0.0 / 1.1.0 / etc.
status:           draft | production | active | deprecated
tier:             audit | advisory | reference | utility
owner:            user_id

body:             text           # the prompt itself
use_case:         string         # one short sentence describing primary use
```

## Contract fields

The contract is what makes a prompt testable. A prompt without a declared output contract is not registerable.

```yaml
contract:
  input_schema:
    required:         Field[]    # what the directive must contain
    optional:         Field[]    # what the directive may contain
    constraints:      Rule[]     # what the directive must NOT do

  output_schema:
    sections:         Section[]  # what sections the output produces
    structured_tail:  JSON_schema  # if there's a JSON object at the end
    invariants:       Rule[]     # testable properties of the output

  failure_modes:
    detected_by:      Detector[] # checks that fire when contract violates
    remediation:      string     # what the user/system does on failure
```

## Dependency fields

Without explicit dependencies, prompts aren't portable.

```yaml
dependencies:
  tools:            string[]     # tool names the prompt requires
  model_class:      frontier | mid | budget | any
  model_specifics:
    minimum:        string       # earliest model that runs at quality
    tested_on:      string[]     # models with eval data
    known_to_break_on: string[]  # models with documented failures
  context_budget:   ContextProfile  # see below
  external:         API[]        # any non-tool external dependencies
  composition:
    calls_prompts:    string[]   # other registered prompts this calls
    called_by:        string[]   # populated automatically when others compose
```

## Context profile (measured, not declared)

This is the field most often gotten wrong. Context budget should be measured from actual runs, not estimated.

```yaml
context_profile:
  prompt_body:           int       # measured token count of the prompt itself

  directive_typical:
    min:               int
    p50:               int
    max:               int

  tool_returns:
    web_search:        {per_call: int, typical_calls: int}
    web_fetch:         {per_call: int, typical_calls: int}
    # etc. per tool

  output_typical:
    min:               int
    p50:               int
    max:               int
    # optionally segmented by model class if outputs vary by model:
    by_model_class:
      grok_class:      {min: int, p50: int, max: int}
      claude_class:    {min: int, p50: int, max: int}
      # etc.

  total_envelope_p50:    int
  total_envelope_p95:    int

  minimum_window:        int
  recommended_window:    int

  cost_per_invocation:
    p50_usd:           float
    p95_usd:           float

  observed_runs:         int       # how many runs informed these numbers
```

## Eval fields

```yaml
evals:
  - id:                 string
    directive:          text       # input
    expected_signals:   Signal[]   # properties the output must have
                                   # NOT exact text matches
    graded_run:
      timestamp:        datetime
      prompt_version:   semver
      output:           text
      grade:            string     # A / A- / B+ / B / C / F
      notes:            text
    regression_check:   bool       # auto-run on version bumps
```

Signals are properties, not literals. Examples that work:
- "At least one lane voted differently from the majority"
- "Every CITED tag links to a real URL"
- "Cross-examination produces ≥1 REBUT_WITH_CITATION or REBUT_WITH_REFINEMENT"

Examples that don't work (too brittle):
- "The output contains the phrase X"
- "The output is exactly N tokens"

## Changelog fields

```yaml
changelog:
  - from_version:     semver
    to_version:       semver
    date:             date
    author:           user_id
    motivation:       text       # why this version exists
    structural_changes: Change[] # what changed in the body
    eval_delta:
      prior_pass_rate:    percent
      new_pass_rate:      percent
      regressions:        Eval[] # tests that now fail
      improvements:       Eval[]
    breaking:           bool
```

## Value surface fields

This is what makes a registry into an asset book rather than a code repo.

```yaml
value_surface:
  invocations:        Invocation[]  # log of runs

  per_invocation:
    cost:             usd
    time:             duration
    output_artifact:  pointer
    user_action:      shipped | discarded | modified | filed

  attributed_value:
    decisions_informed: Decision[]
    estimated_impact:   usd
    citations:          string[]   # "used to kill StrategiAI Path A"

  market:
    licensable:       bool
    list_price:       usd
    licensed_to:      user_id[]
    royalty_terms:    text
```

## Optional fields (recommended)

```yaml
metadata:
  purpose:          text
  invocation_cost:  estimate     # for browsing UIs
  tags:             string[]

lineage:
  composes:         Prompt[]     # prompts this one calls
  forks_from:       Prompt       # if this is a fork of another prompt
  inspired_by:      Prompt[]     # weaker than fork, for credit
```

---

## Tier definitions

**audit** — produces structured analysis with explicit reasoning chains. Examples: consensus_protocol, committee_review. Typically frontier-tier required, multi-section output, citation-discipline binding.

**advisory** — produces direct recommendations without exposing reasoning structure. Examples: standard_advice. Typically mid-tier or budget-tier acceptable, single-section output, lighter contract invariants.

**reference** — composable assets that other prompts call. Examples: industry_playbook_technology. Not runnable standalone. No cost or model fields.

**utility** — single-purpose prompts for specific verification or transformation tasks. Examples: citation_verifier (planned). Often called by audit-tier prompts during evidence-discipline phases.

---

## When a prompt is not eligible for the registry

A prompt should not be registered if:

- The output is unbounded freeform with no testable structure
- The intended use is one-shot (registry overhead exceeds value)
- The prompt is purely conversational with no contract
- The author cannot specify at least one eval signal

The registry is for prompts treated as engineering artifacts. Conversational prompts are perfectly fine; they're just not registry-shaped.
