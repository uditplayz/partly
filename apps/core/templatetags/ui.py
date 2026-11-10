from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def nav_active(context, url_name, exact=False):
    """Return 'is-active' when the current path matches the named URL."""
    request = context.get("request")
    if request is None:
        return ""
    target = reverse(url_name)
    path = request.path
    if exact or target == "/":
        return "is-active" if path == target else ""
    return "is-active" if path.startswith(target) else ""
