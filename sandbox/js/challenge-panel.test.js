import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildChallengeRequest,
  challengeModelOptions,
  productionPrompts,
  summarizeEvent,
  verdictBadge,
} from "./challenge-panel.js";

describe("buildChallengeRequest", () => {
  const form = () => ({
    scenario: "Raise the threshold?",
    rounds: "2",
    maker: { prompt: "fraud-analyst|1.0.0", model: "anthropic|claude-sonnet-5" },
    checker: { prompt: "risk-officer|2.0.0", model: "openai|gpt-4o" },
  });

  it("builds the POST body from form state", () => {
    const { body, error } = buildChallengeRequest(form());
    assert.equal(error, undefined);
    assert.equal(body.scenario, "Raise the threshold?");
    assert.equal(body.rounds, 2);
    assert.deepEqual(body.roles.maker,
      { prompt_id: "fraud-analyst", version: "1.0.0",
        provider: "anthropic", model: "claude-sonnet-5" });
    assert.deepEqual(body.roles.checker,
      { prompt_id: "risk-officer", version: "2.0.0",
        provider: "openai", model: "gpt-4o" });
  });

  it("rejects an empty scenario", () => {
    const state = form();
    state.scenario = "   ";
    assert.match(buildChallengeRequest(state).error, /scenario/i);
  });

  it("rejects a missing role prompt (never silently defaults)", () => {
    const state = form();
    state.checker.prompt = "";
    assert.match(buildChallengeRequest(state).error, /checker/i);
  });

  it("clamps rounds into 1..4", () => {
    const state = form();
    state.rounds = "9";
    assert.equal(buildChallengeRequest(state).body.rounds, 4);
    state.rounds = "0";
    assert.equal(buildChallengeRequest(state).body.rounds, 1);
    state.rounds = "junk";
    assert.equal(buildChallengeRequest(state).body.rounds, 2);
  });
});

describe("productionPrompts", () => {
  it("keeps only production prompts (the server enforces too — 409)", () => {
    const out = productionPrompts([
      { id: "a", version: "1.0.0", status: "production" },
      { id: "b", version: "1.0.0", status: "draft" },
      { id: "c", version: "2.0.0", status: "deprecated" },
    ]);
    assert.deepEqual(out.map((p) => p.id), ["a"]);
  });
});

describe("challengeModelOptions", () => {
  it("puts the owner-default first and derives the rest from config", () => {
    const options = challengeModelOptions({
      "claude-sonnet-4-6": { id: "claude-sonnet-4-6", provider: "anthropic" },
      "gpt-4o": { id: "gpt-4o", provider: "openai" },
    });
    assert.equal(options[0].value, "anthropic|claude-sonnet-5");
    assert.ok(options.some((o) => o.value === "openai|gpt-4o"));
    // no duplicates
    assert.equal(new Set(options.map((o) => o.value)).size, options.length);
  });
});

describe("summarizeEvent", () => {
  it("renders type, actor and summary on one line", () => {
    const line = summarizeEvent({
      type: "ObjectionRaised", actor: "CHECKER",
      summary: "fraud rose 3x", hash: "sha256:" + "ab".repeat(32),
    });
    assert.match(line, /ObjectionRaised/);
    assert.match(line, /CHECKER/);
    assert.match(line, /fraud rose 3x/);
  });

  it("shortens hashes instead of dumping them", () => {
    const line = summarizeEvent({
      type: "PositionTaken", actor: "MAKER", summary: "s",
      hash: "sha256:" + "ab".repeat(32),
    });
    assert.ok(!line.includes("ab".repeat(32)));
    assert.match(line, /abababab/);
  });
});

describe("verdictBadge", () => {
  it("maps PASS/FAIL to badge classes", () => {
    assert.equal(verdictBadge("PASS").cls, "challenge-verdict-pass");
    assert.equal(verdictBadge("FAIL").cls, "challenge-verdict-fail");
    assert.equal(verdictBadge(undefined).label, "—");
  });
});
