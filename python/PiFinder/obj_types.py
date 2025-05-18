# override locally the gettext marker function, i.e. the strings are not translated on load, but extracted. CHECK END OF FILE
def _(key: str) -> str:
    return key


OBJ_TYPES = {
    "Gx": _("Galaxy"),  # TRANSLATORS: Object type
    "OC": _("Open Cluster"),  # TRANSLATORS: Object type
    "Gb": _("Globular"),  # TRANSLATORS: Object type
    "Nb": _("Nebula"),  # TRANSLATORS: Object type
    "DN": _("Dark Nebula"),  # TRANSLATORS: Object type
    "PN": _("Planetary"),  # TRANSLATORS: Object type
    "C+N": _("Cluster + Neb"),  # TRANSLATORS: Object type
    "Ast": _("Asterism"),  # TRANSLATORS: Object type
    "Kt": _("Knot"),  # TRANSLATORS: Object type
    "***": _("Triple star"),  # TRANSLATORS: Object type
    "D*": _("Double star"),  # TRANSLATORS: Object type
    "*": _("Star"),  # TRANSLATORS: Object type
    "?": _("Unkn"),  # TRANSLATORS: Object type
    "Pla": _("Planet"),  # TRANSLATORS: Object type
    "CM": _("Comet"),  # TRANSLATORS: Object type
}

OBJ_TYPE_MARKERS = {
    "Gx": "galaxy",
    "OC": "oc",
    "Gb": "gc",
    "Nb": "neb",
    "PN": "pneb",
    "D*": "dstar",
    "***": "dstar",
    "Ast": "ast",
    "Pla": "planet",
}

# abbreviations and symbols as used in the NGC/IC catalogues
# and in the original Dreyer's book "New General Catalogue of Nebulae and Clusters of Stars"
# see https://ngcicproject.observers.org/abbrev.htm
#
# This German web page gives a German description of the notation used in the NGC/IC catalogues and
# does not translate the abbreviations:
# https://www.astronomische-vereinigung-augsburg.de/artikel/objekte-und-listen/ngc-katalog/
#
# ** So we do not translate the abbreviations, but to keep them in English. **
#
# On 2025-05-04, OBJ_DESCRIPTORS is not used by the software, so it's not translated.
#
OBJ_DESCRIPTORS = {
    "ab": "about",
    "alm": "almost",
    "am": "among",
    "annul": "annular or ring nebula",
    "att": "attached",
    "b": "brighter",
    "bet": "between",
    "biN": "binuclear",
    "bn": "brightest to n side",
    "bs": "brightest to s side",
    "bp": "brightest to p side",
    "bf": "brightest to f side",
    "B": "bright",
    "c": "considerably",
    "chev": "chevelure",
    "co": "coarse, coarsely",
    "com": "cometic (cometary form)",
    "comp": "companion",
    "conn": "connected",
    "cont": "in contact",
    "C": "compressed",
    "Cl": "cluster",
    "d": "diameter",
    "def": "defined",
    "dif": "diffused",
    "diffic": "difficult",
    "dist": "distance, or distant",
    "D": "double",
    "e": "extremely, excessively",
    "ee": "most extremely",
    "er": "easily resolvable",
    "exc": "excentric",
    "E": "extended",
    "f": "following (eastward)",
    "F": "faint",
    "g": "gradually",
    "glob.": "globular",
    "gr": "group",
    "i": "irregular",
    "iF": "irregular figure",
    "inv": "involved, involving",
    "l": "little (adv.); long (adj.)",
    "L": "large",
    "m": "magnitude",
    "M": "middle, or in the middle",
    "n": "north",
    "neb": "nebula",
    "nebs": "nebulous",
    "neby": "nebulosity",
    "nf": "north following",
    "np": "north preceding",
    "ns": "north-south",
    "nr": "near",
    "N": "nucleus, or to a nucleus",
    "pf": "preceding-following",
    "p": "pretty (adv., before F. B. L, S)",
    "pg": "pretty gradually",
    "pm": "pretty much",
    "ps": "pretty suddenly",
    "plan": "planetary nebula (same as PN)",
    "prob": "probably",
    "P": "poor (sparse) in stars",
    "PN": "planetary nebula",
    "r": "resolvable (mottled, not resolved)",
    "rr": "partially resolved, some stars seen",
    "rrr": "well resolved, clearly consisting of stars",
    "R": "round",
    "RR": "exactly round",
    "Ri": "rich in stars",
    "s": "south",
    "sf": "south following",
    "sp": "south preceding",
    "sc": "scattered",
    "sev": "several",
    "st": "stars (pl.)",
    "st 9...": "stars of 9th magnitude and fainter",
    "st 9..13": "stars of mag. 9 to 13",
    "stell": "stellar, pointlike",
    "susp": "suspected",
    "S": "small in angular size",
    "trap": "trapezium",
    "triangle": "triangle, forms a triangle with",
    "triN": "trinuclear",
    "v": "very",
    "vv": "_very_",
    "var": "variable",
    "!": "remarkable",
    "!!": "very much so",
    "!!!": "a magnificent or otherwise interesting object",
}

# Remove local definition and reactivate the global gettext function (that translates)
del _
