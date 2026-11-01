# AgentCAD FreeCAD script. Dimensions in mm. Working hypotheses, not survey data.
# Front faces -Y; X is the bilateral symmetry axis, Z is vertical.
V = Vector
body = Part.makeBox(223000, 18000, 20000, V(-111500, 0, 0))
# Estimated returns: the historical 75 m breadth is not confirmed to refer to
# this footprint. These make an explicitly conjectural U plan.
left = Part.makeBox(18000, 57000, 20000, V(-111500, 18000, 0))
right = Part.makeBox(18000, 57000, 20000, V(93500, 18000, 0))
body = body.fuse(left).fuse(right)
# A shallow full-height central projection is visible in the aerial image.
body = body.fuse(Part.makeBox(66000, 1600, 20000, V(-33000, -1500, 0)))
# Five equal storeys, evenly spaced recessed apertures, approximate only.
cuts = []
for floor in range(5):
    z = 800 + floor * 4000
    for i in range(41):
        x = -108000 + i * 5400
        # Preserve central entrance area at ground floor.
        if floor == 0 and abs(x) < 19000:
            continue
        cuts.append(Part.makeBox(2400, 2800, 2300, V(x, -1600, z)))
for i in range(8):
    cuts.append(Part.makeBox(2600, 3000, 3300, V(-17300 + i * 4000, -1600, 0)))
for cut in cuts:
    body = body.cut(cut)
# Entrance opening count from the historical description. The low-resolution
# aerial image does not establish whether the renovated openings remain arched.
porch = Part.makeBox(36000, 2500, 4300, V(-18000, -3900, 0))
arches = []
for i in range(8):
    x = -16000 + i * 4000
    rect = Part.makeBox(2600, 3000, 3300, V(x-1300, -4100, 0))
    arches.append(rect)
for arch in arches:
    porch = porch.cut(arch)
body = body.fuse(porch)
# Low parapet / cornice: the visible roof is broadly flat.
body = body.fuse(Part.makeBox(224000, 19600, 700, V(-112000, -1600, 19600)))
result = body.removeSplitter()
