from __future__ import annotations

import json
from pathlib import Path

from scripts.qa.baseline_expectations import (
    BROWSER_APP_SMOKE_REQUIRED_MARKERS,
    BROWSER_PLAYWRIGHT_SMOKE_REQUIRED_MARKERS,
    BROWSER_ROOT_REQUIRED_MARKERS,
    BROWSER_UI_SMOKE_REQUIRED_MARKERS,
    REPO_E2E_REQUIRED_SCRIPTS,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_json(rel_path: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / rel_path).read_text(encoding='utf-8'))


def test_root_browser_package_exposes_runnable_repo_scripts() -> None:
    package = _load_json('tests/e2e/package.json')
    scripts = package['scripts']

    assert set(REPO_E2E_REQUIRED_SCRIPTS) <= set(scripts)
    assert 'playwright.root.config.ts' in str(scripts['test:browser'])
    assert 'install chromium' in str(scripts['install:browsers'])


def test_root_browser_entry_keeps_current_error_path_matrix() -> None:
    browser_entry = (REPO_ROOT / 'tests/e2e/test_browser_entry.spec.ts').read_text(encoding='utf-8')

    for marker in BROWSER_ROOT_REQUIRED_MARKERS:
        assert marker in browser_entry
    assert 'repo browser entry survives SSE reconnect' in browser_entry
    assert 'structured 429 marketing errors' in browser_entry
    assert '研究报告文件不存在。' in browser_entry


def test_root_browser_app_smoke_keeps_happy_path_dashboard_and_sessions_slice() -> None:
    app_smoke = (REPO_ROOT / 'tests/e2e/app-smoke.spec.ts').read_text(encoding='utf-8')

    for marker in BROWSER_APP_SMOKE_REQUIRED_MARKERS:
        assert marker in app_smoke
    assert 'dashboard and seeded session history' in app_smoke


def test_root_browser_playwright_smoke_keeps_reload_persistence_slice() -> None:
    smoke_text = (REPO_ROOT / 'tests/e2e/playwright_smoke.spec.ts').read_text(encoding='utf-8')

    for marker in BROWSER_PLAYWRIGHT_SMOKE_REQUIRED_MARKERS:
        assert marker in smoke_text
    assert 'preserves marketing and research task cards across reload' in smoke_text
    assert 'billing workspace usable across reload after one-time refresh recovery' in smoke_text


def test_root_browser_pytest_smoke_tracks_playwright_wiring_and_bootstrap_paths() -> None:
    smoke_text = (REPO_ROOT / 'tests/e2e/test_ui_smoke.py').read_text(encoding='utf-8')
    config_text = (REPO_ROOT / 'tests/e2e/playwright.root.config.ts').read_text(encoding='utf-8')
    readme_text = (REPO_ROOT / 'tests/e2e/README.md').read_text(encoding='utf-8')

    for marker in BROWSER_UI_SMOKE_REQUIRED_MARKERS:
        assert marker in smoke_text
    assert 'app-smoke.spec.ts' in config_text
    assert 'playwright_smoke.spec.ts' in config_text
    assert 'test_browser_entry.spec.ts' in config_text
    assert 'mock-api-server.mjs' in config_text
    assert 'npm --prefix tests/e2e run test:browser' in readme_text
