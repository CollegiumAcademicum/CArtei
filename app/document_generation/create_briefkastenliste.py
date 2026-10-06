"""Render the Briefkastenliste PDF from in-memory resident rows.

Originally a standalone pandas/matplotlib script by Jakob M. Krieger (2024).
Rewritten to run in-process from CArtei data: no CSV round-trip, no
pandas/numpy (numpy's x86-64-v2 baseline broke on the deployment CPU) and no
matplotlib. Only latexmk (via pylatex) and pdfjam remain as subprocesses.

A row is a dict with "forename", "surename" and "flatnumber" (the caller
passes only residents who opted in)."""

import colorsys
import subprocess
from collections import Counter
from pathlib import Path

from pylatex import Command, Document, LargeText, LongTable, MultiColumn, Package
from pylatex.utils import bold, dumps_list, italic


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


def _rainbow_rgb(fraction):
    """Blue->red ramp standing in for matplotlib's 'rainbow' colormap; returns
    an 'r, g, b' string of 0-1 floats for LaTeX \\definecolor."""
    r, g, b = colorsys.hsv_to_rgb((1.0 - fraction) * 2.0 / 3.0, 1.0, 1.0)
    return f"{r:.2f}, {g:.2f}, {b:.2f}"


def build_document(rows, updated):
    """Build the Briefkastenliste LaTeX document. `rows` are opt-in residents,
    `updated` is the date printed as 'Letzte Aktualisierung'."""
    rows = sorted(rows, key=lambda r: _sort_tail(r["surename"]))
    letters = [_sort_tail(r["surename"])[0] for r in rows]
    unique_letters = sorted(set(letters))

    doc = Document(
        default_filepath="briefkastenliste",
        geometry_options={"paperwidth": "9.9cm", "paperheight": "21cm",
                          "inner": ".5cm", "outer": ".5cm", "top": ".5cm", "bottom": "2cm"},
        document_options=["12pt", "twoside", "openleft"],
    )
    doc.preamble.append(Package("biolinum", options=["sfdefault"]))
    doc.preamble.append(Package("xcolor", options=["table"]))
    for i, letter in enumerate(unique_letters):
        fraction = i / max(len(unique_letters) - 1, 1)
        doc.preamble.append(Command("definecolor", [f"rainbow{letter}", "rgb", _rainbow_rgb(fraction)]))

    with doc.create(LongTable("||r|ll||", booktabs=False, row_height=1.3)) as table:
        table.add_hline()
        table.add_row([bold("Sortierung"), bold("Name"), bold("WG")])
        table.add_hline()
        table.end_table_header()
        table.add_row([MultiColumn(3, align="r", data=italic("Fortführung auf nächster Seite..."))])
        table.end_table_footer()
        table.add_row([MultiColumn(3, align="r", data=italic("Auflistung fertig."))])
        table.add_hline()
        table.add_hline()
        table.end_table_last_footer()

        seen = Counter()
        for row, letter in zip(rows, letters):
            wg = _wg(row["flatnumber"])
            initial = row["forename"][0]
            surname = row["surename"].strip()
            cell = f"rainbow{letter}!50"
            if seen[letter] == 0:  # first row of a letter block carries the big letter
                table.add_hline()
                table.add_row([
                    dumps_list([
                        Command("cellcolor", cell),
                        Command("parbox", ["16pt", dumps_list([Command("centering"), LargeText(letter)])], ["c"]),
                    ]),
                    f"{initial}. {surname}",
                    wg,
                ])
            else:
                table.add_row([
                    Command("cellcolor", cell),
                    dumps_list([Command("parbox", ["16pt", f"{initial}."], "t"), surname]),
                    wg,
                ])
            seen[letter] += 1
        table.add_hline()

    doc.append(f"Letzte Aktualisierung: {updated.strftime('%d.%m.%Y')}")
    return doc


def render_pdf(rows, directory, updated):
    """Build and impose (3-up landscape) the Briefkastenliste; return the PDF
    path. Raises subprocess.CalledProcessError / TimeoutExpired / OSError on
    toolchain failure, for the caller to translate into a user-facing error."""
    directory = Path(directory)
    doc = build_document(rows, updated)
    base = directory / "briefkastenliste"
    doc.generate_pdf(filepath=str(base), clean_tex=True, compiler_args=["-f"])
    imposed = directory / "briefkastenliste-pdfjam.pdf"
    subprocess.run(
        ["pdfjam", "--landscape", "--nup", "3x1", f"{base}.pdf", "--outfile", str(imposed)],
        shell=False, check=True, capture_output=True, text=True, timeout=25,
    )
    return imposed
