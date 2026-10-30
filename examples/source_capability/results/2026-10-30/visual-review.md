# Saved production outputs: visual inspection

Product: `b4c04669238e771a0888114f1af3260d7c371834`.
Inputs and raw calls: `output/source-capability/showcase-b4c0466/report.json`
in the evidence archive.
The author and an independent evidence reviewer inspected these actual files.
The independent reviewer also re-rendered each saved PDF through Poppler and
confirmed identical PNG pixels; this verifies the previews' provenance, not
geometric equivalence between different CAD formats.

| Preview | Observations and limits |
|---|---|
| [Mechanical A3](previews/mechanical.png) | Three-step front and longitudinal section, six-hole end view, five BOM rows and linked balloons are legible within the frame. Axial dimensions and title/scale are visible. The template does not label all manufacturing diameters/PCDs and is not a complete manufacturing release. |
| [Mechanical after native activation](previews/mechanical-native.png) | The paper-space `A3 - 1:1` text, model content, frame and table are visible after real DWG conversion, actual AutoCAD CTAB/REGENALL activation and DXFOUT. AgentCAD then exported this PDF. No viewport IDs or geometry were manually rewritten. |
| [Architecture](previews/architecture.png) | Partition, two doors, window, room labels, area/door schedules and exterior dimension chains are legible without clipped labels. Expected room areas round to 26.90 and 44.48 m². |
| [P&ID](previews/pid.png) | Pump, control valve, panel instrument and vessel, process labels and the distinct pneumatic signal line are visible. This is a schematic connectivity example, not an installed-routing drawing. |
| [Tolerance](previews/tolerance.png) | The 35 H7 bore's +0.025/0.000 stack is readable above the dimension line, with a separate units note. Native DIMENSION data and its DWG readback were checked separately. |

Mechanical and tolerance delivery manifests each score 94 with two
`UNDEFINED_LAYER` warnings for `VIEWPORTS`; architecture and P&ID score 100.
These are internal drawing-quality scores, not source-capability or v8 scores.
All output page images correspond to the PDF files; no image editing was used.

AutoCAD's initial inactive paper viewports had id/status 0/0. Actual activation
produced 2/2 in the witness DXF; the raw unactivated file remains in the archive.
This demonstrates the activation path and does not claim automatic inactive-layout
repair by the product. The witness PDF was not produced by an Autodesk PDF driver.

Native readback kept mechanical profiles, BOM, balloons, circles, sections and an
empty engineering critique. AutoCAD may add explicit default DXF tags, so this is
not a claim that every DXF tag or every pre/post-conversion pixel is identical.
