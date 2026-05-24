"""Map jolpica constructor refs to their full sponsored ('real') names.

jolpica returns short names like 'Red Bull' or 'Mercedes'; the official F1
entry names carry the title sponsor (e.g. 'Oracle Red Bull Racing'). For
constructors not in this map we fall back to the short name.
"""

from competitors.models import Constructor

OFFICIAL_TEAM_NAMES: dict[str, str] = {
    # Current grid (2024-2026 era)
    "red_bull": "Oracle Red Bull Racing",
    "mercedes": "Mercedes-AMG Petronas F1 Team",
    "ferrari": "Scuderia Ferrari HP",
    "mclaren": "McLaren Formula 1 Team",
    "aston_martin": "Aston Martin Aramco F1 Team",
    "alpine": "BWT Alpine F1 Team",
    "williams": "Atlassian Williams Racing",
    "rb": "Visa Cash App Racing Bulls F1 Team",
    "racing_bulls": "Visa Cash App Racing Bulls F1 Team",
    "haas": "MoneyGram Haas F1 Team",
    "sauber": "Stake F1 Team Kick Sauber",
    "kick_sauber": "Stake F1 Team Kick Sauber",
    # 2026 newcomers
    "audi": "Audi F1 Team",
    "cadillac": "Cadillac F1 Team",
    # Recent history
    "alfa": "Alfa Romeo F1 Team Stake",
    "alfa_romeo": "Alfa Romeo Racing",
    "alphatauri": "Scuderia AlphaTauri",
    "racing_point": "BWT Racing Point F1 Team",
    "force_india": "Sahara Force India F1 Team",
    "renault": "Renault DP World F1 Team",
    "toro_rosso": "Scuderia Toro Rosso",
}


def official_name(constructor: Constructor) -> str:
    """Return the sponsored entry name if we know it, else the jolpica short name."""
    return OFFICIAL_TEAM_NAMES.get(constructor.ref, constructor.name)
