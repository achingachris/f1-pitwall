"""Fuzzy lookup helpers for /driver and /team queries."""

from django.db.models import Q

from competitors.models import Constructor, Driver


def find_drivers(query: str, limit: int = 10) -> list[Driver]:
    """Return drivers matching the query, ordered most-specific first.

    Match order: exact code → exact ref → exact family_name → contains
    family_name / given_name / ref.
    """
    q = (query or "").strip()
    if not q:
        return []

    code_hit = list(Driver.objects.filter(code__iexact=q))
    if code_hit:
        return code_hit[:limit]
    ref_hit = list(Driver.objects.filter(ref__iexact=q))
    if ref_hit:
        return ref_hit[:limit]
    family_hit = list(Driver.objects.filter(family_name__iexact=q))
    if family_hit:
        return family_hit[:limit]

    # Multi-word: try matching "lewis ham" against given+family combined.
    parts = q.split()
    if len(parts) > 1:
        combined = Driver.objects.filter(
            Q(given_name__icontains=parts[0]) & Q(family_name__icontains=" ".join(parts[1:]))
        )
        combined_hits = list(combined)
        if combined_hits:
            return combined_hits[:limit]

    contains = Driver.objects.filter(
        Q(family_name__icontains=q)
        | Q(given_name__icontains=q)
        | Q(ref__icontains=q)
        | Q(code__icontains=q)
    )
    return list(contains[:limit])


def find_constructors(query: str, limit: int = 10) -> list[Constructor]:
    q = (query or "").strip()
    if not q:
        return []

    ref_hit = list(Constructor.objects.filter(ref__iexact=q))
    if ref_hit:
        return ref_hit[:limit]
    name_hit = list(Constructor.objects.filter(name__iexact=q))
    if name_hit:
        return name_hit[:limit]
    return list(Constructor.objects.filter(Q(name__icontains=q) | Q(ref__icontains=q))[:limit])
