"""Render the Briefkastenliste PDF from in-memory resident rows.

Originally a standalone pandas/matplotlib/LaTeX script by Jakob M. Krieger
(2024). Now rendered in-process with Typst (briefkastenliste.typ): no CSV
round-trip, no subprocesses, no TeX Live in the image (#148).

A row is a dict with "forename", "surename" and "flatnumber" (the caller
passes only residents who opted in)."""

import colorsys
import json
from pathlib import Path

import typst

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "briefkastenliste.typ"
FONTS = HERE / "fonts"

# Fixed row height (briefkastenliste.typ) makes pagination exact: a 21 cm
# strip holds the header and 25 rows; the last one also needs room for
# "Auflistung fertig." and the update date.
ROWS_PER_STRIP = 25
ROWS_ON_LAST_STRIP = 22
STRIPS_PER_SHEET = 3


def _sort_tail(name):
    """Name from its first capital letter on, dropping nobiliary prefixes
    ('von', 'de', 'van') so 'von Humboldt' sorts and groups under 'H'."""
    for i, ch in enumerate(name):
        if ch.isupper():
            return name[i:]
    return name


def _wg(flatnumber):
    """Room name -> WG label: '1.02.3' -> '1.02'. Combined rooms (two current
    assignments joined with ' und ') are truncated per segment."""
    return " und ".join(".".join(seg.split(".")[:2]) for seg in flatnumber.split(" und "))


def _rainbow_hex(fraction):
    """Blue->red ramp (matplotlib's 'rainbow'), mixed 50% with white like the
    original's \\cellcolor{...!50}; returns '#rrggbb'."""
    r, g, b = colorsys.hsv_to_rgb((1.0 - fraction) * 2.0 / 3.0, 1.0, 1.0)
    return "#" + "".join(f"{round((c + 1) / 2 * 255):02x}" for c in (r, g, b))


def build_data(rows, updated):
    """Sorted, coloured and paginated rows for briefkastenliste.typ. `updated`
    is the date printed as 'Letzte Aktualisierung'."""
    rows = sorted(rows, key=lambda r: _sort_tail(r["surename"]))
    letters = [_sort_tail(r["surename"])[0] for r in rows]
    unique = sorted(set(letters))
    colors = {letter: _rainbow_hex(i / max(len(unique) - 1, 1)) for i, letter in enumerate(unique)}

    entries, previous = [], None
    for row, letter in zip(rows, letters):
        entries.append({
            "letter": letter, "show_letter": letter != previous, "new_block": letter != previous,
            "color": colors[letter], "initial": row["forename"][0],
            "surname": row["surename"].strip(), "wg": _wg(row["flatnumber"]),
        })
        previous = letter

    strips, start = [], 0
    while True:
        remaining = len(entries) - start
        if remaining <= ROWS_ON_LAST_STRIP:
            strips.append({"rows": entries[start:], "last": True})
            break
        # Never leave the last strip empty: it carries the closing lines.
        take = ROWS_PER_STRIP if remaining > ROWS_PER_STRIP else remaining - 1
        strips.append({"rows": entries[start:start + take], "last": False})
        start += take
    for number, strip in enumerate(strips, start=1):
        strip["number"] = number
        if strip["rows"]:
            strip["rows"][0] = {**strip["rows"][0], "new_block": False}  # header rule already above
    return {
        "updated": updated.strftime("%d.%m.%Y"),
        "sheets": [strips[i:i + STRIPS_PER_SHEET] for i in range(0, len(strips), STRIPS_PER_SHEET)],
    }


def render_pdf(rows, updated):
    """The imposed (3-up landscape A4) Briefkastenliste as PDF bytes. Raises
    typst.TypstError if the template fails to compile."""
    data = json.dumps(build_data(rows, updated), ensure_ascii=False)
    return typst.compile(
        str(TEMPLATE), format="pdf", font_paths=[str(FONTS)], ignore_system_fonts=True,
        sys_inputs={"data": data},
    )
