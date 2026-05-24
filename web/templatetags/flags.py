"""Template filter for rendering nationality flags inside table cells.

Usage in templates:

    {% load flags %}
    {{ driver.nationality|flag }} {{ driver.family_name }}

The filter is safe to apply to None / "" — it returns an empty string in
that case, so the table cell stays uncluttered for drivers/constructors
with no nationality on record.
"""

from django import template
from django.utils.safestring import mark_safe

from web.nationalities import flag_emoji

register = template.Library()


@register.filter(name="flag")
def flag(nationality: str | None) -> str:
    """Render `<span class="flag">🇬🇧</span> ` for a nationality, or empty."""
    if not nationality:
        return ""
    emoji = flag_emoji(nationality)
    if not emoji:
        return ""
    return mark_safe(f'<span class="flag">{emoji}</span> ')
