import { test } from "node:test";
import assert from "node:assert/strict";
// Import the exact browser module without requiring a Node package manifest.
import fs from "node:fs";
const source = fs.readFileSync(
  new URL("../static/player.js", import.meta.url),
  "utf8",
);
const { imageAt } = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);
test("image boundaries and seeks use the current playback clock", () => {
  for (const [t, want] of [
    [0, 0],
    [2.999, 0],
    [3, 1],
    [7.999, 1],
    [8, -1],
    [12, -1],
    [1, 0],
  ])
    assert.equal(imageAt([3, 5], t), want);
});
test("one image spans the composition", () => {
  assert.equal(imageAt([5], 4.9), 0);
  assert.equal(imageAt([5], 5), -1);
  assert.equal(imageAt([], 0), -1);
});
