#!/usr/bin/env python3
"""Seed genres.json from the one-off Metal Archives harvest.

Metal Archives sits behind a Cloudflare challenge that no HTTP client gets past,
so its data was collected by hand: ma_snippet.js pasted into the Firefox console
on metal-archives.com, which downloads ma-genres.json.

This script turns that dump plus the hand-made disambiguation below into
genres.json, which monitor.py reads. Run it again only to re-seed from a fresh
harvest; day to day monitor.py fills gaps from Spirit of Metal on its own.

    python3 seed_genres.py ~/Downloads/ma-genres.json
"""
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENRES_FILE = HERE / "genres.json"
LINK = re.compile(r'href="([^"]+)"[^>]*>([^<]+)</a>')

MA = "metal-archives"
YO = "propio"  # my own call, because the band has no Metal Archives entry


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


COUNTRY_ES = {
    "Argentina": "Argentina", "United States": "Estados Unidos", "Sweden": "Suecia",
    "United Kingdom": "Reino Unido", "Germany": "Alemania", "Finland": "Finlandia",
    "Netherlands": "Países Bajos", "Italy": "Italia", "France": "Francia",
    "Brazil": "Brasil", "Chile": "Chile", "Norway": "Noruega", "Denmark": "Dinamarca",
    "Spain": "España", "Australia": "Australia", "Poland": "Polonia",
    "Austria": "Austria", "Colombia": "Colombia", "Tunisia": "Túnez",
    "Canada": "Canadá", "Japan": "Japón", "Korea, South": "Corea del Sur",
    "Türkiye": "Türkiye", "Mexico": "México", "Czechia": "Chequia",
}

# --------------------------------------------------------------------------
# How each agenda title resolves. Written by hand once, against the harvest.
#   ma(...)  take it from Metal Archives, optionally pinned to a country
#   man(...) not on Metal Archives, genre is my own call
# --------------------------------------------------------------------------
DUDOSO = "Homónimos en Metal Archives. Elegido por precio y venue del show."
INCIERTO = "Sin resolver: varios homónimos y la agenda no da más datos."

PLAN = {}


def ma(title, query, country=None, name=None, note=""):
    PLAN.setdefault(title, []).append(("ma", query, country, name, note))


def man(title, display, country, genre, note):
    PLAN.setdefault(title, []).append(("man", display, country, genre, note))


for t in [
    "DISLEPSIA", "NEPAL", "WERKEN", "ENTROPHIA", "STEELBALLS", "HELLOWEEN",
    "OLD MAN'S CHILD", "SONATA ARCTICA", "HIGH ON FIRE", "SEPULTURA", "CABRAL",
    "LÖRIHEN", "AMORPHIS", "HELKER", "MORTIIS", "IRON MAIDEN", "APOCALYPTICA",
    "HORCAS", "NOCTURNAL DEPRESSION", "OPERA IX", "MY DYING BRIDE", "RATA BLANCA",
    "DYING FETUS", "FOSSILIZATION", "MYRATH", "DEEP PURPLE", "ELLENDE",
    "THYRFING", "LUCIFERIAN", "RUSH", "ALCEST", "ELEINE", "QUIET RIOT",
    "V.I.D.A.", "DEF LEPPARD", "OPETH", "BENEDICTION", "H2O", "ANGRA",
    "THE HAUNTED", "MALEVOLENT CREATION", "MYSTIC CIRCLE",
]:
    ma(t, t)

# Homónimos resueltos por precio y venue del show.
ma("SATURNUS", "SATURNUS", "Denmark", note=DUDOSO)
ma("GRUESOME", "GRUESOME", "United States", note=DUDOSO)
ma("SPARTA", "SPARTA", "United Kingdom", note=DUDOSO)
ma("UNDERCROFT", "UNDERCROFT", "Chile", note=DUDOSO)
ma("BLOODBATH", "BLOODBATH", "Sweden")
ma("CELESTE", "CELESTE", "France", note=DUDOSO)
ma("KAMIKAZE", "KAMIKAZE", "Argentina", note=DUDOSO)
ma("LETHAL", "LETHAL", "Argentina", note=DUDOSO)
ma("MAD", "MAD", "Argentina", name="Mad", note=DUDOSO)
ma("JASON", "Jason", "Argentina", note=DUDOSO)
ma("NUM", "NUM", "Argentina", note=DUDOSO)
ma("POGROM", "POGROM", "Argentina", note=DUDOSO)
ma("AFTER FOREVER", "AFTER FOREVER", "Netherlands")
ma("HELLBUTCHER", "HELLBUTCHER", "Sweden", note=DUDOSO)
ma("SIX FEET UNDER", "SIX FEET UNDER", "United States")
ma("SARATOGA", "SARATOGA", "Spain", note=DUDOSO)
ma("SLAYER", "SLAYER", "United States")
ma("AVATAR", "AVATAR", "Sweden", note=DUDOSO)
ma("HELLRIPPER", "HELLRIPPER", "United Kingdom")
ma("MORTIFICATION", "MORTIFICATION", "Australia")
ma("POSER", "POSER", "Japan", note="Único match exacto en Metal Archives. Verificar que sea esta banda.")

# Homónimos que no pude resolver.
ma("PENTAGRAM", "PENTAGRAM", "United States",
   note=INCIERTO + " Candidatos: doom de EE.UU., thrash de México, death/thrash de Suecia, el turco (ex-Mezarkabul).")
ma("SANCTUARY", "SANCTUARY", "United States", note=INCIERTO + " Nueve homónimos.")
ma("WARHAMMER", "WARHAMMER", "Chile",
   note=INCIERTO + " Diez homónimos y ninguno argentino. Puse el chileno por cercanía y precio.")
man("DIES IRAE", "Dies Irae", "sin dato", "sin dato",
    "Quince homónimos en Metal Archives y ninguno argentino. La entrada de 20.000 sugiere una banda local sin ficha.")
man("NATAS", "Los Natas", "Argentina", "Stoner Metal",
    "Metal Archives no tiene ningún «Natas» argentino. El que encaja es Los Natas, de Buenos Aires.")
man("LEFT TO DIE", "Left to Die", "Estados Unidos", "Death metal (repertorio de Death)",
    "Proyecto de ex-integrantes de Death. Los «Left to Die» de Metal Archives son otras bandas.")

# Shows con varias bandas en el título.
ma("EPICA & RHAPSODY", "EPICA", "Netherlands")
ma("EPICA & RHAPSODY", "RHAPSODY OF FIRE", "Italy", note="La agenda dice «Rhapsody» a secas.")
ma("RHAPSODY OF FIRE & MASTERPLAN", "RHAPSODY OF FIRE", "Italy")
ma("RHAPSODY OF FIRE & MASTERPLAN", "MASTERPLAN", "Germany")
ma("MALEVOLENT CREATION & MYSTIC CIRCLE", "MALEVOLENT CREATION")
ma("MALEVOLENT CREATION & MYSTIC CIRCLE", "MYSTIC CIRCLE")
ma("ELLENDE & THYRFING", "ELLENDE")
ma("ELLENDE & THYRFING", "THYRFING")
ma("TESTAMENT, MUNICIPAL WASTE & IMMOLATION", "TESTAMENT", "United States")
ma("TESTAMENT, MUNICIPAL WASTE & IMMOLATION", "MUNICIPAL WASTE")
ma("TESTAMENT, MUNICIPAL WASTE & IMMOLATION", "IMMOLATION", "United States")
ma("VIRTHUAL, BALLES & ARHIMAN", "VIRTHUAL")
ma("VIRTHUAL, BALLES & ARHIMAN", "BALLES")
ma("VIRTHUAL, BALLES & ARHIMAN", "ARHIMAN")
man("MEMPHIS MAY FIRE & BLESSTHEFALL", "Memphis May Fire", "Estados Unidos", "Metalcore",
    "No está en Metal Archives.")
man("MEMPHIS MAY FIRE & BLESSTHEFALL", "Blessthefall", "Estados Unidos", "Post-hardcore",
    "No está en Metal Archives.")

# Solistas: el género sale de la ficha de su banda principal.
ma("TARJA", "Tarja", "Finland")
ma("BLAZE BAYLEY", "Blaze Bayley")
ma("MARTY FRIEDMAN", "Marty Friedman")
ma("DOYLE", "Doyle")
ma("METALOCALYPSE: DETHKLOK", "Dethklok")
ma("BERTONCELLI: 25° ANIVERSARIO DE \"PAZ EN LA TORMENTA\"", "Bertoncelli")
ma("MAGNOS POR JAVIER BARROZO", "Magnos")
ma("ZABALA & FREZZA -EL RELOJ-", "El Reloj", note="Ficha de El Reloj.")
ma("ZAMARBIDE", "V8", "Argentina", note="Ex-cantante de V8.")
ma("CTM CLAUDIO TANO MARCIELLO", "Almafuerte", note="Ex-guitarrista de Almafuerte.")
ma("PAUL GILBERT", "Racer X", note="Su banda, Racer X.")
ma("ROBERTO TIRANTI", "Labyrinth", "Italy", note="Cantante de Labyrinth.")
ma("GEOFF TATE", "Queensryche", "United States", name="Queensrÿche", note="Ex-cantante de Queensrÿche.")
ma("ROY KHAN", "Kamelot", note="Ex-cantante de Kamelot.")
ma("CHARLOTTE WESSELS", "Delain", note="Ex-cantante de Delain.")
ma("ANETTE OLZON", "Nightwish", note="Ex-cantante de Nightwish.")
ma("FLOOR JANSEN", "Nightwish", note="Cantante de Nightwish.")
ma("LA H NO MURIÓ", "Hermetica", "Argentina", name="Hermética", note="Tributo a Hermética.")
man("MICHALE GRAVES", "Michale Graves", "Estados Unidos", "Horror punk",
    "Ex-cantante de Misfits, que no está en Metal Archives.")
man("JOHN 5", "John 5", "Estados Unidos", "Shred instrumental / hard rock",
    "Ex-Marilyn Manson y Mötley Crüe. No está en Metal Archives.")
man("DREGEN", "Dregen", "Suecia", "Sleaze rock / punk 'n' roll",
    "Guitarrista de Backyard Babies. No está en Metal Archives.")

# Tributos: el género es el de la banda homenajeada.
man("AMAZING - TRIBUTO A AEROSMITH", "Tributo a Aerosmith", "Argentina", "Hard rock",
    "Banda tributo. Aerosmith no está en Metal Archives.")
man("BLACK DOG - THE LED ZEPPELIN EXPERIENCE", "Tributo a Led Zeppelin", "Argentina",
    "Hard rock / blues rock", "Banda tributo. Led Zeppelin no está en Metal Archives.")
man("EXPERIENCIA QUEEN", "Tributo a Queen", "Argentina", "Rock",
    "Banda tributo. Queen no está en Metal Archives.")
man("KISS MY ASS", "Tributo a Kiss", "Argentina", "Hard rock / shock rock",
    "Banda tributo. Kiss no está en Metal Archives.")
man("ZAKK SABBATH", "Zakk Sabbath", "Estados Unidos", "Doom / heavy metal",
    "Proyecto de Zakk Wylde tocando Black Sabbath. No está en Metal Archives.")
man("ENTRE EL CIELO Y EL INFIERNO", "Tributo a Rata Blanca", "Argentina",
    "Heavy/Power Metal, Hard Rock", "Es el título de un disco de Rata Blanca.")

# Festivales: el line-up solo figura en el flyer, que es una imagen.
man("BLACK METAL EDITION 2", "Festival", "Argentina", "Black metal",
    "Line-up solo en el flyer. El género sale del nombre del festival.")
man("UN MANDATO DIVINO 8", "Festival", "Argentina", "sin dato",
    "Line-up solo en el flyer.")

# Sin ficha en Metal Archives: género puesto por mí.
for t, c, g in [
    ("A PERFECT CIRCLE", "Estados Unidos", "Rock alternativo / art rock"),
    ("A SKYLIT DRIVE", "Estados Unidos", "Post-hardcore / metalcore"),
    ("A WILHELM SCREAM", "Estados Unidos", "Melodic hardcore / skate punk"),
    ("AL DI MEOLA", "Estados Unidos", "Jazz fusión / guitarra acústica"),
    ("ALTER BRIDGE", "Estados Unidos", "Hard rock / metal alternativo"),
    ("ANTIMATTER", "Reino Unido", "Dark rock / rock progresivo atmosférico"),
    ("BABY METAL", "Japón", "Kawaii metal"),
    ("BETWEEN THE BURIED AND ME", "Estados Unidos", "Metal progresivo / death metal técnico"),
    ("CRASHDÏET", "Suecia", "Sleaze / glam metal"),
    ("DIE TOTEN HOSEN", "Alemania", "Punk rock"),
    ("FELIX MARTIN", "Venezuela", "Fusión instrumental / metal progresivo"),
    ("FISHBONE", "Estados Unidos", "Funk rock / ska punk"),
    ("FIT FOR A KING", "Estados Unidos", "Metalcore"),
    ("FOO FIGHTERS", "Estados Unidos", "Rock alternativo"),
    ("GODSPEED YOU! BLACK EMPEROR", "Canadá", "Post-rock"),
    ("ILL NIÑO", "Estados Unidos", "Nu metal / metal latino"),
    ("LANDMVRKS", "Francia", "Metalcore"),
    ("LIVE", "Estados Unidos", "Rock alternativo"),
    ("NICO BORIE", "Chile", "Covers de anime en rock / metal"),
    ("SLAUGHTER TO PREVAIL", "Rusia", "Deathcore"),
    ("SOCIAL DISTORTION", "Estados Unidos", "Punk rock / cowpunk"),
    ("SOEN", "Suecia", "Metal progresivo"),
    ("THE CRUEL INTENTIONS", "Noruega", "Sleaze / hard rock"),
    ("TOE", "Japón", "Math rock / post-rock"),
    ("YOUTH OF TODAY", "Estados Unidos", "Youth crew hardcore"),
    ("ZZ TOP", "Estados Unidos", "Blues rock / hard rock"),
]:
    man(t, t.title(), c, g, "No está en Metal Archives.")

# Argentinas chicas sin ficha que tampoco conozco. No invento el género.
for t in ["CYNARA", "DARLOTODO", "REQUIEM FOR EDEN", "RITUAL DE BRUJAS", "SONNE LICHT"]:
    man(t, t.title(), "Argentina (probable)", "sin dato",
        "No está en Metal Archives y no la conozco.")


def build(harvest_path):
    harvest = json.load(open(harvest_path, encoding="utf-8"))

    def rows(q):
        out = []
        for r in harvest.get(q) or []:
            if isinstance(r, list) and (m := LINK.search(r[0])):
                out.append({"name": m.group(2).strip(), "url": m.group(1),
                            "genre": r[1], "country": r[2]})
        return out

    def pick(q, country, name):
        cands = [r for r in rows(q) if norm(r["name"]) == norm(name or q)]
        if country:
            cands = [r for r in cands if r["country"] == country] or cands
        return cands[0] if cands else None

    bands, missing = {}, []
    for title, steps in PLAN.items():
        acts = []
        for step in steps:
            if step[0] == "ma":
                _, q, country, name, note = step
                row = pick(q, country, name)
                if not row:
                    missing.append(f"{title} -> {q}")
                    continue
                acts.append({
                    "name": row["name"],
                    "country": COUNTRY_ES.get(row["country"], row["country"]),
                    "genre": row["genre"],
                    "url": row["url"],
                    "source": MA,
                    "note": note,
                })
            else:
                _, display, country, genre, note = step
                acts.append({"name": display, "country": country, "genre": genre,
                             "url": "", "source": YO, "note": note})
        if acts:
            bands[title] = {"acts": acts, "resolved_at": date.today().isoformat()}

    return bands, missing


def main():
    harvest_path = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "Downloads" / "ma-genres.json")
    bands, missing = build(harvest_path)

    existing = {}
    if GENRES_FILE.exists():
        existing = json.load(open(GENRES_FILE, encoding="utf-8")).get("bands", {})
    # Never clobber what monitor.py resolved on its own for bands we do not cover.
    merged = dict(existing)
    merged.update(bands)

    GENRES_FILE.write_text(
        json.dumps({"version": 1, "bands": merged}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"{len(bands)} títulos sembrados desde {harvest_path}")
    print(f"{len(merged)} títulos en total en {GENRES_FILE.name}")
    if missing:
        print(f"\n{len(missing)} sin match en el harvest:")
        for m in missing:
            print("  -", m)


if __name__ == "__main__":
    main()
