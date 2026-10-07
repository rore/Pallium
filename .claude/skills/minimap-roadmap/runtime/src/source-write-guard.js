import { AsyncLocalStorage } from "node:async_hooks";

const currentGuard = new AsyncLocalStorage();

export function withSourceWriteGuard(guard, work, pathGuard = null) {
  return currentGuard.run({ guard, pathGuard }, work);
}

export async function assertSourceWriteGuard() {
  await currentGuard.getStore()?.guard();
}

export async function assertSourceWritePath(candidate) {
  await currentGuard.getStore()?.pathGuard?.(candidate);
}
