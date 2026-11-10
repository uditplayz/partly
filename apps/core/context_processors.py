from django.conf import settings


def site(request):
    return {
        "csp_nonce": getattr(request, "csp_nonce", ""),
        "SITE_NAME": settings.SITE_NAME,
        "PLATFORM_FEE": settings.PLATFORM_LISTING_FEE_INR,
        "PWA_THEME_COLOR_LIGHT": settings.PWA_THEME_COLOR_LIGHT,
        "PWA_THEME_COLOR_DARK": settings.PWA_THEME_COLOR_DARK,
    }
