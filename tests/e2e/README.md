# Repo Browser Smoke

`tests/e2e/` carries the repo-level browser smoke entry for SmartCloud-X.

## Coverage in the root Playwright entry

- login and dashboard bootstrap through the current `apps/web-user/` app
- one-time `401` refresh recovery in the billing workspace
- route-level permission denial when the user lacks `user:marketing.read`
- chat SSE interruption followed by automatic reconnect
- citation-detail `403` permission denial UX
- marketing `429` structured error UX

## No-browser wiring smoke

The owned pytest layer also validates the root browser wiring without launching Chromium:

```bash
python -m pytest -q tests/e2e/test_ui_smoke.py
```

That smoke checks the committed repo wrapper, Playwright config, and browser entry markers.

## Runnable browser entry

```bash
npm --prefix tests/e2e run test:browser
```

If a fresh runner is missing browser dependencies, bootstrap them from `apps/web-user/` first:

```bash
npm --prefix apps/web-user ci
npm --prefix tests/e2e run install:browsers
```

The root `scripts/qa/run_full_stack_validation.sh` wrapper will run the same entry when `SMARTCLOUD_QA_RUN_BROWSER=1` is set.
