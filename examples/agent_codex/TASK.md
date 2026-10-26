You are testing a CAD runtime exposed to you ONLY through the MCP server "agentcad". Do not run shell commands; use only agentcad MCP tools.

Task:
1. Call list_operations to learn the operation catalog.
2. Create drawing "bracket.dxf" (units mm) and draw, using apply_operations with low-level operations (do NOT use draw_from_spec):
   a 100 x 60 mm mounting plate (closed outline on layer OUTLINE, lower-left corner at 0,0),
   four holes of diameter 8 mm whose centers are 10 mm from the two adjacent edges (layer HOLES),
   and linear dimensions for the overall width and height plus a diameter dimension for one hole (layer DIM).
3. Call validate_drawing with explicit requirements (outline 100x60 on layer OUTLINE, the four holes, the dimensions). If anything fails or an operation returns an error, read the structured error and fix it, then validate again.
4. Then change the plate width to 120 mm while keeping each hole center 10 mm from its adjacent edges (choose suitable operations, e.g. stretch), update requirements accordingly, and validate again.
5. Call get_diff and read_drawing, then get_metrics.
Finish with a short report: tool calls you made, any errors you hit and how you fixed them, and the final validation result (passed true/false with the numbers).
