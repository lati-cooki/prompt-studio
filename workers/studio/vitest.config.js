// vitest.config.js — @cloudflare/vitest-pool-workers 0.18.x pairs with
// vitest 4 and exposes cloudflareTest as a Vite PLUGIN (defineWorkersConfig
// is gone). Wrangler config supplies compat date/flags and the DO binding;
// the miniflare block injects the test-only operator bearer secret, the
// URL-base vars the assertions pin, and the HUB stub: an auxiliary worker
// (test/hub-stub.js) exposing the HubInternal entrypoint contract from
// src/hub.js, bound exactly the way the real threadhub-cf service will be.
import { defineConfig } from 'vitest/config';
import { cloudflareTest } from '@cloudflare/vitest-pool-workers';

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: './wrangler.jsonc' },
      miniflare: {
        bindings: {
          STUDIO_OPERATOR_TOKEN: 'test-operator-token',
          PUBLIC_BASE_URL: 'https://studio.example',
          HUB_PUBLIC_BASE_URL: 'https://hub.example',
          OBJECT_RATE: '10/60',
        },
        serviceBindings: {
          HUB: { name: 'hub-stub', entrypoint: 'HubInternal' },
        },
        workers: [
          {
            name: 'hub-stub',
            modules: true,
            scriptPath: './test/hub-stub.js',
            compatibilityDate: '2026-07-01',
            compatibilityFlags: ['nodejs_compat'],
          },
        ],
      },
    }),
  ],
});
