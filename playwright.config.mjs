/* The page harness only; tests/views.smoke.mjs runs against a live appliance by hand. */
export default { testDir: "tests", testMatch: /.*\.spec\.mjs$/, timeout: 20000, use: { headless: true } };
