"""
Content Security Policy middleware.

Builds the ``Content-Security-Policy`` response header from the directive
tuples defined in ``settings.py``. Views can override individual directives
per-response by setting ``response.csp_overrides = {"CSP_FRAME_ANCESTORS": "*"}``
(using the uppercase settings name as the key) — the widget view uses this to
allow itself to be embedded in iframes on other sites, while every other page
stays locked down.

A per-request nonce is generated for ``script-src`` so the one inline script
(the Tailwind config object in base.html) can be allowed *by nonce* instead of
``'unsafe-inline'``. In production (DEBUG off) ``'unsafe-inline'`` is dropped
from ``script-src`` entirely; in dev it is kept for convenience (a nonce takes
precedence over ``'unsafe-inline'`` per the CSP spec, so the nonce still
governs). Inline *styles* still need ``'unsafe-inline'`` while the Tailwind
Play CDN is in use, because it injects a generated ``<style>`` at runtime;
production should build Tailwind locally to remove that (see README).

A couple of related security headers are also set here so they live in one
place: ``X-Content-Type-Options``, ``Referrer-Policy``, ``Permissions-Policy``.
"""

import secrets

from django.conf import settings


# Map settings.CSP_* names to CSP directive names.
_DIRECTIVE_SETTINGS = [
    ("CSP_DEFAULT_SRC", "default-src"),
    ("CSP_SCRIPT_SRC", "script-src"),
    ("CSP_STYLE_SRC", "style-src"),
    ("CSP_IMG_SRC", "img-src"),
    ("CSP_FONT_SRC", "font-src"),
    ("CSP_CONNECT_SRC", "connect-src"),
    ("CSP_FRAME_ANCESTORS", "frame-ancestors"),
    ("CSP_BASE_URI", "base-uri"),
    ("CSP_FORM_ACTION", "form-action"),
]


def _build_csp_header(overrides, nonce):
    """Render the CSP header string from settings + per-response overrides.

    ``nonce`` (per-request) is injected into script-src so the inline Tailwind
    config script can run without 'unsafe-inline'. In production 'unsafe-inline'
    is stripped from script-src; the nonce is the sole inline-script allow-list.
    """
    parts = []
    for setting_name, directive in _DIRECTIVE_SETTINGS:
        if setting_name in overrides:
            value = overrides[setting_name]
        else:
            value = getattr(settings, setting_name, None)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            sources = list(value)
        else:
            sources = [str(value)]

        if directive == "script-src" and nonce:
            # Production: drop 'unsafe-inline' so inline scripts need the nonce.
            if not settings.DEBUG:
                sources = [s for s in sources if s != "'unsafe-inline'"]
            sources.append(f"'nonce-{nonce}'")

        parts.append(f"{directive} {' '.join(sources)}")
    return "; ".join(parts)


class ContentSecurityPolicyMiddleware:
    """Inject the Content-Security-Policy header on every response.

    Generates a per-request nonce and attaches it to ``request.csp_nonce`` (made
    available to templates via the ``csp_nonce`` context processor) so inline
    scripts can carry ``nonce="{{ csp_nonce }}"`` instead of relying on a
    blanket ``'unsafe-inline'``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate the nonce before the view runs so templates can read it via
        # the context processor during rendering.
        request.csp_nonce = secrets.token_urlsafe(16)

        response = self.get_response(request)

        # Allow views to override individual directives per-response.
        overrides = getattr(response, "csp_overrides", {}) or {}

        # Set CSP always (not only when DEBUG is off) so the widget's
        # frame-ancestors override takes effect in dev too.
        response["Content-Security-Policy"] = _build_csp_header(
            overrides, request.csp_nonce
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )
        return response
