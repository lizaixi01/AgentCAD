# 操作 × 测试矩阵 (自动生成)

统计每个操作在哪些测试文件中以 `"op": "<name>"` 形式被调用。
这只说明“被执行过”，断言质量见各测试本身。

| 操作 | 类别 | 测试文件 |
|---|---|---|
| `add_angular_dim` | annotate | test_autocad_findings.py, test_h_operations.py |
| `add_arc` | draw | test_autocad_findings.py, test_h_operations.py, test_i_common_ops.py |
| `add_center_mark` | annotate | test_i_common_ops.py |
| `add_circle` | draw | test_autocad_findings.py, test_b_revision.py, test_constraints.py, test_d_errors.py, test_f_repro_recovery.py, test_g_interfaces.py, test_h_operations.py, test_i_common_ops.py |
| `add_diameter_dim` | annotate | test_autocad_findings.py, test_h_operations.py, test_layouts_and_scripts.py |
| `add_donut` | draw | test_i_common_ops.py |
| `add_ellipse` | draw | test_h_operations.py |
| `add_hatch` | draw | test_i_common_ops.py |
| `add_leader` | annotate | test_h_operations.py |
| `add_line` | draw | test_autocad_findings.py, test_constraints.py, test_d_errors.py, test_h_operations.py, test_i_common_ops.py, test_layouts_and_scripts.py, test_security.py |
| `add_linear_dim` | annotate | test_autocad_findings.py, test_b_revision.py, test_f_repro_recovery.py, test_h_operations.py |
| `add_mtext` | annotate | test_h_operations.py, test_i_common_ops.py |
| `add_ordinate_dim` | annotate | test_i_common_ops.py |
| `add_point` | draw | test_autocad_findings.py, test_constraints.py, test_d_errors.py, test_f_repro_recovery.py, test_h_operations.py, test_layouts_and_scripts.py, test_security.py |
| `add_polygon` | draw | test_i_common_ops.py |
| `add_polyline` | draw | test_h_operations.py, test_i_common_ops.py |
| `add_radius_dim` | annotate | test_autocad_findings.py, test_h_operations.py |
| `add_ray` | draw | test_i_common_ops.py |
| `add_rectangle` | draw | test_autocad_findings.py, test_b_revision.py, test_d_errors.py, test_f_repro_recovery.py, test_g_interfaces.py, test_h_operations.py, test_i_common_ops.py, test_layouts_and_scripts.py |
| `add_spline` | draw | test_h_operations.py |
| `add_table` | annotate | test_h_operations.py |
| `add_text` | annotate | test_autocad_findings.py, test_b_revision.py, test_h_operations.py, test_i_common_ops.py, test_layouts_and_scripts.py |
| `add_title_block` | annotate | test_autocad_findings.py, test_h_operations.py |
| `add_viewport` | layout | test_layouts_and_scripts.py |
| `add_xline` | draw | test_i_common_ops.py |
| `array_polar` | edit | test_h_operations.py |
| `array_rect` | edit | test_h_operations.py, test_security.py |
| `break` | edit | test_i_common_ops.py |
| `chamfer` | edit | test_h_operations.py |
| `copy` | edit | test_h_operations.py, test_layouts_and_scripts.py |
| `create_layer` | layer | test_f_repro_recovery.py, test_h_operations.py |
| `create_layout` | layout | test_layouts_and_scripts.py |
| `create_text_style` | annotate | test_i_common_ops.py |
| `define_block` | block | test_autocad_findings.py, test_h_operations.py, test_i_common_ops.py |
| `delete` | edit | test_f_repro_recovery.py, test_h_operations.py, test_layouts_and_scripts.py, test_security.py |
| `delete_layer` | layer | test_h_operations.py |
| `draw_order` | edit | test_i_common_ops.py |
| `explode` | edit | test_h_operations.py |
| `extend` | edit | test_h_operations.py |
| `fillet` | edit | test_h_operations.py |
| `insert_block` | block | test_autocad_findings.py, test_h_operations.py, test_i_common_ops.py |
| `join` | edit | test_i_common_ops.py |
| `mirror` | edit | test_autocad_findings.py, test_h_operations.py |
| `modify` | edit | test_h_operations.py, test_layouts_and_scripts.py |
| `modify_layer` | layer | test_h_operations.py |
| `move` | edit | test_d_errors.py, test_f_repro_recovery.py, test_h_operations.py |
| `offset` | edit | test_autocad_findings.py, test_h_operations.py |
| `purge` | edit | test_i_common_ops.py |
| `rotate` | edit | test_h_operations.py |
| `scale` | edit | test_h_operations.py |
| `set_annotation_scale` | annotate | test_autocad_findings.py |
| `set_attributes` | block | test_h_operations.py |
| `set_properties` | edit | test_h_operations.py |
| `stretch` | edit | test_b_revision.py, test_h_operations.py |
| `trim` | edit | test_autocad_findings.py, test_d_errors.py, test_h_operations.py |

共 55 个操作，未被任何测试调用: 无
