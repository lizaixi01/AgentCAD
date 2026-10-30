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
| Counterbore diameter except M14 | [Ifanger cutting-tool catalogue](https://www.ifanger.com/content/freetext/Kataloge/03_Zerspanungswerkzr_stand_en/files/assets/common/downloads/publication.pdf?uni=f8a17257f4e8ef27ca8be03386f07be4), 03/2006, p. 32, DIN 974-1 table | Ten stored diameters agree. M14 is absent; its separate source below does not change the authority of the other rows. |
| Counterbore depth except M14 | [Schraube & Mutter drilling table](https://schraube-mutter.de/bohrtabelle-fuer-zylinderschrauben/), ISO 4762 depth row only | Ten clearance recommendations without washers. This supplier page has discrepancies in other rows, so only these depths are used; no claim of full DIN conformity. |
| M14 counterbore diameter and depth | [GOST 12876-67 scan](https://files.stroyinf.ru/Data/28/2834.pdf), amendment 4 (1983), figure 4 on printed p. 4 and table 4 continuation on printed p. 5 / PDF pp. 5–6 | Washer-free hexagon-socket cylindrical head: **D = 24, t = 15**. The new nominal depth replaces 14.6. These are the D/t columns, not D1/t1/t2. The through hole retains its separate ISO 273 source; complete DIN/GOST conformity is not asserted. |

Independent numeric expectations in `tests/test_standard_sources.py` protect the
checked facts and test unsupported-size refusal, provenance through the public
tool, and unit conversion into a saved drawing. M14 returns
`reference_status: dimensions_checked_mixed_references` and a source for each
dimension. Other counterbores retain `diameter_checked_depth_recommended`.
Existing drawings and historical assessment evidence are not rewritten: an old
14.6 mm depth does not acquire the new 15 mm source merely by updating metadata.

## M14 interpretation and limits

The [official catalogue](https://protect.gost.ru/gost/details/52f30749-edee-4bc3-92d1-5dcdc4b3bba2)
and [amendment record](https://protect.gost.ru/gost/changesdetails/4282860c-8faa-4e4c-ab70-0b53136bbd88)
identify amendment 4, registered 1983-04-14 and effective 1984-01-01. The inspected
PDF is a third-party-hosted reproduction of the standard, not an authenticated
official electronic edition. An independent reviewer checked both the figure and
column headings against the M14 row; the scan is identified below and not bundled.

The full standard also specifies H14 on D/t, a maximum internal corner radius
of 0.3 mm and, for this case, a 0.5 × 45° seat/through-hole chamfer (clause 4).
Clause 6 refers through holes to GOST 11284-75. Its amended M14 row contains
15 / 16 (15.5) / 17 (16.5); parenthesized values are not recommended. AgentCAD
deliberately retains **15.5 mm from the independently cited ISO 273 medium series**.
The 2D symbol neither applies the GOST tolerance bands nor models its chamfer and
corner. It is therefore a mixed-reference nominal drawing, not a fully compliant
GOST hole. Clause 8 permits increased depths; it does not justify reducing 15 to 14.6.

WASI's ISO 4762 M14 head has dk = 21 and k(max) = 14 mm. The selected 24 × 15
nominals leave 1.5 mm radial and 1 mm axial space relative to those head dimensions.
That is a geometric check, not a fit, tolerance-stack or manufacturing certificate.

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
| GOST 12876-67 scan with amendment 4 | `36ef405c0034672efa231a949ab3c1d793f2c6a060c571bb917afb4360b132b7` |
