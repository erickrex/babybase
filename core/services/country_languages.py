"""Shared country-to-language mapping utility.

Single source of truth for ISO 3166-1 alpha-2 country code to language code mappings.
Used by both qdrant_client.py (bridge candidate filtering) and relevance.py (bridge scoring).
"""

COUNTRY_LANGUAGES: dict[str, set[str]] = {
    "DE": {"de"},
    "US": {"en"},
    "GB": {"en"},
    "ES": {"es"},
    "MX": {"es"},
    "FR": {"fr"},
    "IT": {"it"},
    "RU": {"ru"},
    "BR": {"pt"},
    "PT": {"pt"},
    "NL": {"nl"},
    "SE": {"sv"},
    "NO": {"no"},
    "DK": {"da"},
    "PL": {"pl"},
    "CZ": {"cs"},
    "JP": {"ja"},
    "CN": {"zh"},
    "KR": {"ko"},
    "IN": {"hi", "en"},
    "CA": {"en", "fr"},
    "CH": {"de", "fr", "it"},
    "BE": {"nl", "fr", "de"},
    "AT": {"de"},
    "AR": {"es"},
    "CO": {"es"},
    "CL": {"es"},
    "PE": {"es"},
    "UA": {"uk"},
    "TR": {"tr"},
    "GR": {"el"},
    "IL": {"he"},
    "SA": {"ar"},
    "EG": {"ar"},
}


def get_country_languages(country_code: str) -> set[str]:
    """Return the set of primary language codes for a given country code.

    Args:
        country_code: ISO 3166-1 alpha-2 country code (e.g. "DE", "US").

    Returns:
        Set of language codes (e.g. {"de"}, {"en", "fr"}), or empty set if
        the country code is empty or not recognized.
    """
    if not country_code:
        return set()
    return COUNTRY_LANGUAGES.get(country_code.upper(), set())
