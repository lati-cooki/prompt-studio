import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { extractPromptBody, listLoadablePrompts } from "./registry.js";

describe("extractPromptBody", () => {
  it("extracts section after The prompt body marker", () => {
    const md = `# Title

## The prompt body

You are a helpful agent.

Do things.`;
    assert.equal(extractPromptBody(md), "You are a helpful agent.\n\nDo things.");
  });

  it("strips leading horizontal rule after marker", () => {
    const md = `## The prompt body

---

Hello.`;
    assert.equal(extractPromptBody(md), "Hello.");
  });

  it("falls back to content after last ---", () => {
    const md = `# Meta

---

Fallback body here.`;
    assert.ok(extractPromptBody(md).includes("Fallback body"));
  });
});

describe("listLoadablePrompts", () => {
  it("filters prompts without file", () => {
    const out = listLoadablePrompts([
      { id: "a", version: "1.0", file: "p/a.md", status: "production" },
      { id: "b", version: "1.0", file: null, status: "production" },
    ]);
    assert.equal(out.length, 1);
    assert.equal(out[0].id, "a");
  });

  it("defaults to production and active, excludes draft", () => {
    const prompts = [
      { id: "a", version: "1.0.0", file: "a.md", status: "production" },
      { id: "c", version: "1.0.0", file: "c.md", status: "active" },
      { id: "b", version: "1.0.0", file: "b.md", status: "draft" },
    ];
    const out = listLoadablePrompts(prompts);
    assert.deepEqual(out.map((p) => p.id), ["a", "c"]);
  });

  it("includes drafts when asked (nightly), plus production and active", () => {
    const prompts = [
      { id: "a", version: "1.0.0", file: "a.md", status: "production" },
      { id: "c", version: "1.0.0", file: "c.md", status: "active" },
      { id: "b", version: "1.0.0", file: "b.md", status: "draft" },
    ];
    const out = listLoadablePrompts(prompts, true);
    assert.deepEqual(out.map((p) => p.id), ["a", "b", "c"]);
  });

  it("never includes deprecated prompts, even with includeDrafts", () => {
    const prompts = [
      { id: "a", version: "1.0.0", file: "a.md", status: "production" },
      { id: "d", version: "1.0.0", file: "d.md", status: "deprecated" },
    ];
    assert.deepEqual(listLoadablePrompts(prompts).map((p) => p.id), ["a"]);
    assert.deepEqual(listLoadablePrompts(prompts, true).map((p) => p.id), ["a"]);
  });
});