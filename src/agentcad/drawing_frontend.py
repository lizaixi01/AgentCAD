"""Use DXF block-reference properties for DIMENSION graphics in every preview."""
from ezdxf.addons.drawing import Frontend


class DrawingFrontend(Frontend):
    def draw_composite_entity(self, entity, properties) -> None:
        # ezdxf applies the reference context to INSERT, but its generic virtual
        # entity path leaves DIMENSION graphics on literal layer 0 / BYBLOCK.
        # Resolve these graphics in the dimension's context just as AutoCAD does.
        if entity.dxftype() != "DIMENSION":
            return super().draw_composite_entity(entity, properties)
        self.ctx.push_state(properties)
        try:
            super().draw_composite_entity(entity, properties)
        finally:
            self.ctx.pop_state()
