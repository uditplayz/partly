from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "PWA_THEME_COLOR_LIGHT": settings.PWA_THEME_COLOR_LIGHT,
        "PWA_THEME_COLOR_DARK": settings.PWA_THEME_COLOR_DARK,
    }
