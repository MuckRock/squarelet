# Standard Library
import re
from pathlib import Path

# Third Party
import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

# Standalone pages and files that cannot load the Vite bundle.
EXEMPT = {
    # Email clients drop external stylesheets.
    "core/email/base.html",
    # Django admin does not load the Vite bundle.
    "admin/dropdown_filter.html",
    # OIDC session iframe is a standalone document.
    "oidc_provider/check_session_iframe.html",
    # Never included by any template.
    "forms/layout/field_file.html",
}

# `<script src=...>` and `<script type="application/json">` carry no code of our own.
INLINE = re.compile(
    r"<style\b|<script\b(?![^>]*\bsrc=)(?![^>]*application/json)", re.IGNORECASE
)


def _templates():
    return sorted(
        path
        for path in TEMPLATES.rglob("*.html")
        if str(path.relative_to(TEMPLATES)) not in EXEMPT
    )


@pytest.mark.parametrize(
    "path", _templates(), ids=lambda p: str(p.relative_to(TEMPLATES))
)
def test_templates_load_styles_and_scripts_from_frontend(path):
    """Styles and scripts live in `frontend/`; templates load them with `vite_asset`."""
    assert not INLINE.search(path.read_text())
