// package/minimap/ui/spec/index.js
//
// Single entry point for wiring the spec subsystem. Bundles the two wire
// calls so app.js can initialize render + composer with one call. The
// individual modules (anchors, render, composer) keep their own named
// exports — app.js continues to import the symbols it needs directly from
// each leaf so the dependency graph stays flat and module loading stays
// quick on first paint.

import { wireSpecRender } from "/spec/render.js";
import { wireSpecComposer } from "/spec/composer.js";

// Wire render + composer in one shot. Pass the union of DOM elements and
// helpers either side needs; each module only captures what it uses, so
// passing extras is harmless.
export function initSpec({ dom, state, api, helpers }) {
  wireSpecRender({ dom, state, api, helpers });
  wireSpecComposer({ dom, state, api, helpers });
}
