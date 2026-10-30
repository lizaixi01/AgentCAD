# 操作 × 测试矩阵 (自动生成)

统计每个操作在哪些测试文件中以 `"op": "<name>"` 形式被调用。
这只说明“被执行过”，断言质量见各测试本身。三维零件操作只统计 test_n_parts.py（二维和三维有同名操作）。

| 操作 | 类别 | 测试文件 |
|---|---|---|
| `add_angular_dim` | annotate | test_autocad_findings.py, test_h_operations.py |
| `add_arc` | draw | test_autocad_findings.py, test_h_operations.py, test_i_common_ops.py, test_t_workflow_guards.py |
| `add_center_mark` | annotate | test_i_common_ops.py |
| `add_circle` | draw | test_autocad_findings.py, test_b_revision.py, test_constraints.py, test_d_errors.py, test_f_repro_recovery.py, test_g_interfaces.py, test_h_operations.py, test_i_common_ops.py, test_j_compact_results.py, test_k_pdf.py, test_l_fewer_turns.py, test_l_live_session.py, test_m_library.py, test_p_busy_files.py, test_q_viewer_progress.py, test_t_workflow_guards.py, test_w_delivery.py, test_y_tolerances.py |
| `add_datum_feature` | library | test_m_library.py |
| `add_diameter_dim` | annotate | test_autocad_findings.py, test_h_operations.py, test_layouts_and_scripts.py, test_y_tolerances.py |
| `add_donut` | draw | test_i_common_ops.py |
| `add_ellipse` | draw | test_h_operations.py |
| `add_feature_control_frame` | library | test_m_library.py |
| `add_hatch` | draw | test_i_common_ops.py, test_t_workflow_guards.py |
| `add_leader` | annotate | test_h_operations.py |
| `add_line` | draw | test_autocad_findings.py, test_constraints.py, test_d_errors.py, test_h_operations.py, test_i_common_ops.py, test_j_compact_results.py, test_layouts_and_scripts.py, test_m_library.py, test_o_viewer.py, test_p_busy_files.py, test_q_viewer_progress.py, test_security.py, test_t_workflow_guards.py, test_y_tolerances.py, test_z_locking.py |
| `add_linear_dim` | annotate | test_autocad_findings.py, test_b_revision.py, test_f_repro_recovery.py, test_h_operations.py, test_t_workflow_guards.py, test_y_tolerances.py |
| `add_mtext` | annotate | test_h_operations.py, test_i_common_ops.py |
| `add_ordinate_dim` | annotate | test_i_common_ops.py |
| `add_pid_symbol` | library | test_m_library.py |
| `add_point` | draw | test_autocad_findings.py, test_constraints.py, test_d_errors.py, test_f_repro_recovery.py, test_h_operations.py, test_l_fewer_turns.py, test_l_live_session.py, test_layouts_and_scripts.py, test_security.py |
| `add_polygon` | draw | test_i_common_ops.py |
| `add_polyline` | draw | test_h_operations.py, test_i_common_ops.py, test_t_workflow_guards.py |
| `add_process_line` | library | test_m_library.py |
| `add_radius_dim` | annotate | test_autocad_findings.py, test_h_operations.py |
| `add_ray` | draw | test_i_common_ops.py |
| `add_rectangle` | draw | test_autocad_findings.py, test_b_revision.py, test_d_errors.py, test_f_repro_recovery.py, test_g_interfaces.py, test_h_operations.py, test_i_common_ops.py, test_k_pdf.py, test_layouts_and_scripts.py, test_m_library.py, test_q_viewer_progress.py, test_t_workflow_guards.py |
| `add_spline` | draw | test_h_operations.py, test_j_compact_results.py |
| `add_standard_hole` | library | test_m_library.py |
| `add_standard_part` | library | test_m_library.py |
| `add_surface_finish` | library | test_m_library.py |
| `add_table` | annotate | test_h_operations.py |
| `add_text` | annotate | test_autocad_findings.py, test_b_revision.py, test_h_operations.py, test_i_common_ops.py, test_k_pdf.py, test_l_fewer_turns.py, test_layouts_and_scripts.py, test_q_viewer_progress.py |
| `add_title_block` | annotate | test_autocad_findings.py, test_h_operations.py |
| `add_viewport` | layout | test_k_pdf.py, test_l_fewer_turns.py, test_layouts_and_scripts.py |
| `add_xline` | draw | test_i_common_ops.py |
| `array_polar` | edit | test_h_operations.py, test_l_fewer_turns.py |
| `array_rect` | edit | test_h_operations.py, test_security.py |
| `block_from_entities` | block | test_t_workflow_guards.py |
| `break` | edit | test_i_common_ops.py |
| `chamfer` | edit | test_h_operations.py, test_r_part_scripts.py |
| `change_space` | layout | **无** |
| `copy` | edit | test_h_operations.py, test_layouts_and_scripts.py |
| `create_layer` | layer | test_f_repro_recovery.py, test_h_operations.py, test_q_viewer_progress.py |
| `create_layout` | layout | test_k_pdf.py, test_l_fewer_turns.py, test_layouts_and_scripts.py |
| `create_text_style` | annotate | test_i_common_ops.py |
| `define_block` | block | test_autocad_findings.py, test_h_operations.py, test_i_common_ops.py, test_t_workflow_guards.py |
| `delete` | edit | test_f_repro_recovery.py, test_h_operations.py, test_layouts_and_scripts.py, test_m_library.py, test_security.py |
| `delete_layer` | layer | test_h_operations.py |
| `draw_arch_plan` | engineering | test_u_engineering.py, test_w_delivery.py |
| `draw_mechanical_assembly` | engineering | test_u_engineering.py, test_w_delivery.py |
| `draw_order` | edit | test_i_common_ops.py |
| `draw_pid` | engineering | test_u_engineering.py, test_w_delivery.py |
| `edit_hatch` | edit | test_t_workflow_guards.py |
| `explode` | edit | test_h_operations.py |
| `extend` | edit | test_h_operations.py |
| `fillet` | edit | test_h_operations.py, test_q_viewer_progress.py, test_r_part_scripts.py |
| `insert_block` | block | test_autocad_findings.py, test_h_operations.py, test_i_common_ops.py, test_t_workflow_guards.py |
| `join` | edit | test_i_common_ops.py |
| `mirror` | edit | test_autocad_findings.py, test_h_operations.py |
| `modify` | edit | test_h_operations.py, test_j_compact_results.py, test_layouts_and_scripts.py, test_y_tolerances.py |
| `modify_layer` | layer | test_h_operations.py |
| `move` | edit | test_d_errors.py, test_f_repro_recovery.py, test_h_operations.py, test_j_compact_results.py, test_t_workflow_guards.py |
| `offset` | edit | test_autocad_findings.py, test_h_operations.py |
| `purge` | edit | test_i_common_ops.py |
| `remove_duplicates` | edit | test_t_workflow_guards.py |
| `rotate` | edit | test_h_operations.py |
| `scale` | edit | test_h_operations.py |
| `set_annotation_scale` | annotate | test_autocad_findings.py |
| `set_attributes` | block | test_h_operations.py |
| `set_page_setup` | layout | **无** |
| `set_properties` | edit | test_h_operations.py |
| `stretch` | edit | test_b_revision.py, test_h_operations.py |
| `trace_boundary` | draw | **无** |
| `trim` | edit | test_autocad_findings.py, test_d_errors.py, test_h_operations.py |
| `add_sketch` | part_sketch | test_n_parts.py |
| `chamfer` | part_feature | test_n_parts.py |
| `delete_feature` | part_edit | test_n_parts.py |
| `fillet` | part_feature | test_n_parts.py |
| `groove` | part_feature | test_n_parts.py |
| `helix` | part_feature | test_n_parts.py |
| `hole` | part_feature | test_n_parts.py |
| `linear_pattern` | part_feature | test_n_parts.py |
| `loft` | part_feature | test_n_parts.py |
| `mirror` | part_feature | test_n_parts.py |
| `modify_feature` | part_edit | test_n_parts.py |
| `pad` | part_feature | test_n_parts.py |
| `pocket` | part_feature | test_n_parts.py |
| `polar_pattern` | part_feature | test_n_parts.py |
| `primitive` | part_feature | test_n_parts.py |
| `revolve` | part_feature | test_n_parts.py |
| `set_parameters` | part_edit | test_n_parts.py |
| `sweep` | part_feature | test_n_parts.py |
| `thickness` | part_feature | test_n_parts.py |

共 90 个操作，未被任何测试调用: ['change_space (layout)', 'set_page_setup (layout)', 'trace_boundary (draw)']
