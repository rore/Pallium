// package/minimap/ui/spec/index.js
//
// Single entry point for wiring the spec subsystem. Bundles the three
// wire calls (render + composer + toc) so app.js can initialize the
// whole subsystem with one call. The individual modules keep their own
// named exports — app.js continues to import only the symbols it needs
// directly from each leaf so the dependency graph stays flat and module
// loading stays quick on first paint.

import { wireSpecRender } from "/spec/render.js";
import { wireSpecComposer } from "/spec/composer.js";
import { wireSpecToc } from "/spec/toc.js";

// Wire render + composer + toc in one shot. Each module captures only
// what it uses, so passing the union of dom/state/api/helpers is harmless.
export function initSpec({ dom, state, api, helpers }) {
  wireSpecRender({ dom, state, api, helpers });
  wireSpecComposer({ dom, state, api, helpers });
  wireSpecToc({ dom, state, api, helpers });
}
