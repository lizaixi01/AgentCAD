# Dimensional library source audit

Checked 2026-10-30. This covers every stored row of `PITCH`, `HEX_S`, `BOLT_K`,
`NUT_M`, `WASHER`, `SHCS`, `BEARINGS`, `CLEARANCE`, `TAP_DRILL` and `COUNTERBORE`
in `stdlib.py`. The supported fastener sizes are **M3, M4, M5, M6, M8, M10, M12,
M14, M16, M20 and M24**, not every intervening size. Bearings cover 6000–6010,
6200–6210 and 6300–6310. All values are millimetres. Unknown sizes are refused;
there is no extrapolation. `standard_library` returns provenance and scope.

These are drawing dimensions, not a certificate that a manufactured part meets
every clause of a standard. Catalogue dimensions, normative dimensions and shop
recommendations have different authority. Source PDFs are linked, not redistributed.
An unstated edition stays unstated; the retrieval date does not become its edition.

| Stored values | Checked source and location | Scope and qualifications |
|---|---|---|
| Coarse pitch, hex width `s`, nut height `m` | [ISO 4032:2012](https://ssmalloys.com/wp-content/uploads/2024/10/ISO-4032.pdf), tables 1–2, printed pp. 2–3 / PDF pp. 8–9 | All 11 rows. `m` is **maximum**, `s` nominal. This is the 2012 edition, not a claim of conformance to ISO 4032:2023. |
| Bolt head height `k` | [JF Engineering ISO 4017 dimensional datasheet](https://www.jfeindia.com/iso-4017.html), size/`k` table | All 11 nominal rows; supplier gives no edition. Widths independently agree with the source above. Thread lengths/chamfers are not certified by this check. |
| Washer `d1,d2,h` | [WASI DIN 125 A / similar ISO 7089](https://www.wasishop.de/pdf_datenblatt/din125a_en.pdf), p. 1 | All 11 nominal rows; no edition stated. Does not verify hardness, material or full tolerance bands. |
| Socket screw `dk,k,s` | [WASI BPL2005 DIN 912 / EN ISO 4762](https://www.wasi.bg/media/5407/din912a2.pdf), p. 1 | All 11 rows; `k` maximum. M14/M16 and M18/M20 are paired columns. Diagram is simplified, not the complete fastener standard. |
| Bearing `d,D,B` | [Timken E10857-GB](https://www.timken.com/wp-content/uploads/2023/06/E10857-GB.pdf), table 1, printed p. 2 / PDF p. 4 | All 33 rows. Outer dimensions only; excludes load ratings, internal geometry, seals and fit selection. |
| Clearance fine/medium/coarse | [NBK clearance-hole reference](https://www.nbk1560.com/en-US/resources/other/article/technical-20-diameter-of-clearance-holes-and-counterbores-for-bolts-and-screws/), clearance table / ISO 273 note, published 2015-06-18 | All 11 rows agree with the stored ISO 273 size series. These are clearance series, **not** ISO 286 dimensional fits. |
| Cutting-tap pilot drill | [EXACT GS52](https://exact.info/en/innovations/premium-thread-cutting-assortment/), 2020-10-01, M3–M12; [Thürmer core-hole recommendations](https://www.thurmer.com/special-sizes-faq/), M14/M16/M20/M24 | All 11 recommendations. EXACT supplies 10.2 for M12; Thürmer recommends 10.25. Either can be a process choice; the library uses 10.2. Not for forming taps; material and engagement affect selection. No unverified claim of ISO 2306 conformity. |
| Counterbore diameter | [Ifanger cutting-tool catalogue](https://www.ifanger.com/content/freetext/Kataloge/03_Zerspanungswerkzr_stand_en/files/assets/common/downloads/publication.pdf?uni=f8a17257f4e8ef27ca8be03386f07be4), 03/2006, p. 32, DIN 974-1 table | Ten stored diameters agree. **M14 is absent**: its legacy 24 mm diameter remains an explicitly unverified engineering clearance, not a verified DIN row. |
| Counterbore depth | [Schraube & Mutter drilling table](https://schraube-mutter.de/bohrtabelle-fuer-zylinderschrauben/), ISO 4762 depth row only | Eleven clearance recommendations without washers. This supplier page has discrepancies in other rows, so only its depth row is used; no claim that the whole page or these depths establish DIN conformity. M14 remains unverified as a normative counterbore. |

Independent numeric expectations in `tests/test_standard_sources.py` protect the
checked facts and test unsupported-size refusal, provenance through the public
tool, and unit conversion into a saved drawing. The exceptional M14 counterbore
returns `reference_status: unverified_counterbore`; verified diameters still label
depths as recommendations. Existing geometry is preserved rather than silently
reclassifying a legacy recommendation as certified data.

The generated fastener's minor diameter, hex-corner construction, chamfer,
thread-length approximations and bearing internals are drawing conventions.
The audit does **not** certify those formulas, GD&T interpretation, ISO/ISA symbol
completeness, surface texture, material strength or manufacturing suitability.
Numeric ISO 286 fits have their own [bounded, sourced table](fit-tables.md).

## Retrieved file fingerprints

These SHA-256 values identify the files inspected locally; the files themselves
are not included. HTML sources may change even when their URL does not.

| Source | SHA-256 |
|---|---|
| ISO 4032:2012 PDF | `89ed2e502fc037416e437cefb20c97f8d25e75aadade53d0e07adfbedd31d1cf` |
| JF Engineering HTML | `cb8060832082d3e1ef25da57ea6e701267fb7d12a8b7dd0a01e81a4058d8d126` |
| WASI washer PDF | `a6cbf9ff22a4529aa389a2dd6356928d0ffc5941dbd1768b18bc7fb456d89e68` |
| WASI socket screw PDF | `b169940bd3cc874defa1d7fa023fee968dd8df29f39e9d7146ce41a02e2bf893` |
| Timken PDF | `41fd6b2fdf4904d155014b6aa5aeb5e4ed3d2212d9b3cc5f312d28d34dddc495` |
| Thürmer HTML | `d022f753d3ad66febe995252c0daa798cfa857f7c1bcf382ad29ce47b898c8f9` |
| Ifanger 03/2006 PDF | `499a7bc0e067d0b577df40350bf13e2bcf165e5282b512c6c06dab7be5dcff4a` |
