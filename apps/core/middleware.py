"""Security headers that Django doesn't set on its own: a Content-Security-Policy with a
per-request nonce, and a Permissions-Policy that allows the camera only for our own pages
(the door scanner needs it)."""
import secrets

from django.conf import settings

FONT_STYLE_HOST = "https://fonts.googleapis.com"
FONT_FILE_HOST = "https://fonts.gstatic.com"
RAZORPAY_HOSTS = ("https://checkout.razorpay.com", "https://api.razorpay.com", "https://lumberjack.razorpay.com")

PERMISSIONS_POLICY = "camera=(self), microphone=(), geolocation=(), payment=()"


def build_policy(nonce, *, razorpay=False):
    script = ["'self'", f"'nonce-{nonce}'"]
    style = ["'self'", FONT_STYLE_HOST]
    connect = ["'self'"]
    img = ["'self'", "data:", "blob:"]
    frame = ["'none'"]
    if razorpay:
        # Razorpay's checkout.js injects its own styles and opens its own frame. Only the
        # checkout page gets this wider policy.
        script.append(RAZORPAY_HOSTS[0])
        style.append("'unsafe-inline'")
        connect += RAZORPAY_HOSTS
        img.append("https:")
        frame = list(RAZORPAY_HOSTS[:2])
    directives = {
        "default-src": ["'self'"],
        "script-src": script,
        "style-src": style,
        "font-src": ["'self'", FONT_FILE_HOST],
        "img-src": img,
        "media-src": ["'self'", "blob:"],
        "connect-src": connect,
        "frame-src": frame,
        "manifest-src": ["'self'"],
        "worker-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


# The service worker's own fetches (fonts) are governed by the policy on /serviceworker.js,
# not by the page's policy, so it needs its own.
SERVICE_WORKER_POLICY = (
    f"default-src 'self'; connect-src 'self' {FONT_STYLE_HOST} {FONT_FILE_HOST}; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        if not settings.CSP_ENABLED or request.path.startswith("/admin/"):
            return response  # the Django admin ships its own inline pieces; staff-only
        if request.path == "/serviceworker.js":
            policy = SERVICE_WORKER_POLICY
        else:
            policy = build_policy(request.csp_nonce, razorpay=getattr(request, "csp_razorpay", False))
        header = "Content-Security-Policy-Report-Only" if settings.CSP_REPORT_ONLY else "Content-Security-Policy"
        response.setdefault(header, policy)
        return response
