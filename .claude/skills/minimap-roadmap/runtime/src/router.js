// Tiny method+regex route matcher. Pulled out so unit tests can import it
// without booting the HTTP server (server.js auto-starts on import — that's
// how the launcher script triggers it).
//
// Each `route` is `{ method, pattern, handler }` where `pattern` is a RegExp
// matched against the URL pathname. Returns `{ handler, params }` (params is
// the array of regex captures) on a match, or `null`.

export function matchRoute(routes, method, pathname) {
  for (const route of routes) {
    if (route.method !== method) continue;
    const match = pathname.match(route.pattern);
    if (match) {
      return { handler: route.handler, params: match.slice(1) };
    }
  }
  return null;
}
