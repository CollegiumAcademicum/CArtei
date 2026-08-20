from app.models import DamageLine

# line value -> (short label, kind). kind drives which buckets show.
DAMAGE_META = {
    DamageLine.BODEN_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.BODEN_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.FUSSLEISTE_FLECKEN.value: ("Flecken Fußleiste", "flecken"),
    DamageLine.WAND_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.WAND_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.WAND_KLEBER.value: ("Kleberückstände", "kleber"),
    DamageLine.TUER_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.TUER_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.FENSTER_RAHMEN_FLECKEN.value: ("Flecken Fensterrahmen", "flecken"),
    DamageLine.FENSTER_BANK_FLECKEN.value: ("Flecken Fensterbank", "flecken"),
    DamageLine.FENSTER_KLEBER.value: ("Kleberückstände", "kleber"),
    DamageLine.BETT_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.BETT_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.MATRATZE_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.SCHREIBTISCH_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.SCHREIBTISCH_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.SCHRANK_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.SCHRANK_LOECHER.value: ("Löcher", "loecher"),
}

# Bucket column -> label, per kind. loecher hides count_mid.
BUCKETS = {
    "flecken": [("count_lt1", "<1 cm"), ("count_mid", "1–5 cm"), ("count_gt", ">5 cm")],
    "kleber":  [("count_lt1", "<1 cm"), ("count_mid", "1–5 cm"), ("count_gt", ">5 cm")],
    "loecher": [("count_lt1", "<1 cm"), ("count_gt", ">1 cm")],
}

_D = DamageLine
STEPS = [
    {"slug": "allgemein", "title": "Allgemeine Angaben", "header": ["mv_representative", "protocol_at"]},
    {"slug": "zwischenwand", "title": "Position der Zwischenwand", "header": ["partition_position", "barrierefrei"]},
    {"slug": "boden", "title": "Zimmer – Boden", "lines": [_D.BODEN_FLECKEN.value, _D.BODEN_LOECHER.value, _D.FUSSLEISTE_FLECKEN.value]},
    {"slug": "waende", "title": "Zimmer – Wände", "lines": [_D.WAND_FLECKEN.value, _D.WAND_LOECHER.value, _D.WAND_KLEBER.value]},
    {"slug": "tuer", "title": "Zimmer – Tür", "lines": [_D.TUER_FLECKEN.value, _D.TUER_LOECHER.value]},
    {"slug": "fenster", "title": "Zimmer – Fenster", "lines": [_D.FENSTER_RAHMEN_FLECKEN.value, _D.FENSTER_BANK_FLECKEN.value, _D.FENSTER_KLEBER.value]},
    {"slug": "bett", "title": "Zimmer – Bett", "header": ["bed_source"], "lines": [_D.BETT_FLECKEN.value, _D.BETT_LOECHER.value]},
    {"slug": "matratze", "title": "Matratze", "header": ["mattress_source"], "lines": [_D.MATRATZE_FLECKEN.value]},
    {"slug": "schreibtisch", "title": "Schreibtisch", "header": ["desk_source"], "lines": [_D.SCHREIBTISCH_FLECKEN.value, _D.SCHREIBTISCH_LOECHER.value]},
    {"slug": "schrank", "title": "Schrank", "header": ["closet_source"], "lines": [_D.SCHRANK_FLECKEN.value, _D.SCHRANK_LOECHER.value]},
    {"slug": "sonstige_schaeden", "title": "Sonstige Schäden", "header": ["sonstige_schaeden"]},
    {"slug": "sonstige_moebel", "title": "Sonstige Möbel", "header": ["sonstige_moebel"]},
    {"slug": "kueche", "title": "Küche – Schäden", "header": ["kueche_schaeden"]},
    {"slug": "bad", "title": "Bad – Schäden", "header": ["bad_schaeden"]},
    {"slug": "gemeinschaftsflaeche", "title": "Gemeinschaftsfläche", "header": ["gemeinschaftsflaeche"]},
]


def protocol_lines():
    return list(DAMAGE_META.keys())
