#!/bin/sh
# 1. install the packages when they are missing or package.json / bun.lock changed since the last install
# 2. wait for the backend (its first start loads the data and can take several minutes), then start the dev server
set -eu

stamp=node_modules/.install-stamp
want=$(cat package.json bun.lock | sha256sum | cut -d' ' -f1)

if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$want" ]; then
  echo "[frontend] installing packages (bun install) ..."
  # Bun's default of 48 parallel downloads overwhelms Docker Desktop's DNS ("DNSResolveFailed"): fewer at a time, and one retry.
  bun install --frozen-lockfile --network-concurrency "${BUN_NETWORK_CONCURRENCY:-6}" \
    || { echo "[frontend] install failed, trying once more ..."; bun install --frozen-lockfile --network-concurrency 3; }
  echo "$want" > "$stamp"
fi

if [ -n "${API_URL:-}" ] && [ "${WAIT_FOR_BACKEND:-1}" = "1" ]; then
  node -e '
    const url = process.env.API_URL + "/api/chatbot/status";
    const started = Date.now();
    (async () => {
      for (let waited = 0; ; waited += 5) {
        try { await fetch(url, { signal: AbortSignal.timeout(4000) }); process.exit(0); } catch {}
        if (waited % 30 === 0) console.log(`[frontend] waiting for the backend (the first start loads data, this can take a few minutes) ... ${Math.round((Date.now() - started) / 1000)}s`);
        if (waited > 3600) { console.log("[frontend] the backend never answered; starting anyway"); process.exit(0); }
        await new Promise((r) => setTimeout(r, 5000));
      }
    })();
  '
fi

echo "[frontend] ready: http://localhost:${FRONTEND_PORT:-5173}"
exec "$@"
