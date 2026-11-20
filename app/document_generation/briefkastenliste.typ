// Briefkastenliste: 9.9 × 21 cm strips, three per landscape A4 sheet.
// All data (already sorted and paginated, see create_briefkastenliste.py)
// arrives as JSON in sys.inputs.data, so names are never parsed as markup.
#let data = json(bytes(sys.inputs.data))
#let row-h = 0.67cm

#set document(title: "Briefkastenliste")
#set page(paper: "a4", flipped: true, margin: 0pt)
#set text(font: "Linux Biolinum O", size: 12pt, lang: "de")

#let header = (
  table.hline(stroke: 0.6pt),
  align(center, strong[Sortierung]), strong[Name], strong[WG],
  table.hline(stroke: 0.6pt),
)

#let entry(r) = (
  table.cell(fill: rgb(r.color), align(right + horizon,
    if r.show_letter { text(size: 17pt, r.letter) })),
  [#box(width: 16pt)[#r.initial.] #r.surname],
  r.wg,
)

#let strip(s) = box(width: 9.9cm, height: 21cm,
  inset: (x: 0.5cm, top: 0.5cm, bottom: 2cm), {
  // Outer double rule (the LaTeX original's "||r|ll||").
  block(stroke: (x: 0.4pt), inset: (x: 1.6pt), table(
    columns: (2.6cm, 3.35cm, 1fr),
    rows: row-h,
    align: left + horizon,
    inset: (x: 5pt, y: 0pt),
    stroke: (x, y) => (
      left: if x == 0 { 0.4pt } else if x == 1 { 0.4pt },
      right: if x == 2 { 0.4pt },
    ),
    ..header,
    ..s.rows.map(r => (
      ..if r.new_block { (table.hline(stroke: 0.4pt),) },
      ..entry(r),
    )).flatten(),
    ..if s.last { (table.hline(stroke: 0.4pt),) },
  ))
  v(-0.6em)
  if s.last {
    align(right, emph[Auflistung fertig.])
    v(-0.5em)
    line(length: 100%, stroke: 0.6pt)
    v(0.6em)
    h(0.5em)
    [Letzte Aktualisierung: #data.updated]
  }
})

#for (i, sheet) in data.sheets.enumerate() {
  if i > 0 { pagebreak() }
  stack(dir: ltr, ..sheet.map(strip))
}
