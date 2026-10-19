#!/usr/bin/env node
// Set the filesystem worker default before loading the ESM launcher.
if (!Object.hasOwn(process.env, "UV_THREADPOOL_SIZE")) process.env.UV_THREADPOOL_SIZE = "8";
import("./start-server.mjs").catch((error) => {
  process.nextTick(() => { throw error; });
});
