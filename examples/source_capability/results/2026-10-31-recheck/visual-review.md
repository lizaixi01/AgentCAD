# Visual review of the repaired 290ced3 production outputs

Product: `290ced3033f85e1fc97611cf1c920d922524bc3a`. Inspected 2026-10-31 by the
implementation agent, separately from structural validation. The independent
scoring reviewer records its own inspection. This is not manufacturing certification.

All seven saved one-page PDFs were freshly rendered with Poppler at a maximum
dimension of 2,000 pixels and individually opened. `preview-render-290ced3.json`
records renderer/version, commands, PDF and PNG hashes and pixel dimensions.

| Preview | Direct observation |
|---|---|
| mechanical.png | A3 frame/title block fit. Stepped section hatching, lengths 18/24/13 and total 55, outside diameters 48/60/42 and bore 25 THRU are readable. Cap diameter 70, thickness 12, 6X diameter 6.6, PCD 52, equal spacing 60 degrees / first 30 degrees, five BOM rows and balloons are visible. |
| mechanical-native.png | The same supplied dimensions, section, hole callouts, five-row BOM and A3 geometry remain readable after the actual DWG roundtrip and layout activation. No critical clipping or text collision observed. |
| mechanical-variant.png | Distinct lengths 17.5/23/11 and total 51.5, outside diameters 42/60/34 and bore 19 THRU are readable. Flange diameter 86, thickness 14 and bore 18 THRU are clear, as are 8X diameter 8.4, PCD 64 and spacing 45 degrees / first 22.5 degrees. Separate M14 detail shows diameter 15.5, counterbore diameter 24 depth 15, and the explicit mixed ISO/GOST nominal-reference note. Two BOM rows fit. |
| mechanical-variant-native.png | Fractional dimensions, eight-hole layout, M14 detail, reference-boundary note and two-row BOM remain readable after native roundtrip and A3 activation. |
| architecture.png | Wall and room boundaries, doors D11/D12, window W11, room labels 26.90 / 44.48 m2 and schedules are clear. The 11240 overall width, 7240 overall height, dimension chains and 1000/900 door widths fit without clipped text. |
| pid.png | P-11, CV-11, V-11, FC 11, DN80-SUPPLY and DN80-FEED are legible. The dashed signal connection is distinguishable from the process lines; no clipped endpoint or obscured label observed. |
| tolerance.png | Diameter 35 H7 and stacked +0.025 / 0.000 deviations are readable above the dimension line. The separate bore/shaft units note is visible and within the page. |

No critical text clipping or text-on-text collision was observed in these seven
pages. Mechanical leaders cross associated part geometry while leaving the note
text clear. View/note placement comes from the supplied example specifications;
this does not establish universal automatic layout. Unspecified hole depths,
machining operations, surface finish and tolerances are not inferred or certified.
The M14 detail explicitly depicts mixed-reference nominal dimensions.

The native witness uses actual CTAB/REGENALL/DXFOUT. Raw inactive viewport id/status
0/0 and the active 2/2 witness are retained; IDs were not patched for plotting.
AgentCAD exports these PDFs, not Autodesk's PDF driver. Visual readability is
distinct from geometric equivalence, exact pixel equality or intermediate-opacity
intensity parity between formats.

Mechanical, mechanical-variant and tolerance delivery quality remains 94, with
two undefined-VIEWPORTS-layer warnings each; architecture and P&ID quality is 100.
Those metrics are separate from source-capability points and the v8 result.
