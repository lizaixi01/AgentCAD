"""Generate and independently check flange DXFs; ezdxf + Python stdlib only."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import ezdxf
from ezdxf import bbox, units
from ezdxf.math import Vec3

ROOT = Path(__file__).resolve().parent
DATA = """part,outer,bore,pcd,count,hole,material
FL-101,150,60,110,6,12,Q235
FL-102,180,75,135,8,14,Q235
FL-103,120,40,90,4,11,45钢
FL-104,200,90,160,8,18,Q345
FL-105,160,60,120,6,14,Q235
FL-106,100,30,70,4,9,304不锈钢
FL-107,220,110,180,12,14,Q235
FL-108,140,50,105,6,11,45钢
FL-109,130,60,118,6,14,Q235
FL-110,250,120,200,16,18,Q345
FL-111,90,40,66,16,14,Q235
FL-112,170,80,130,8,13,304不锈钢
"""


def read_rows():
    rows = list(csv.DictReader(io.StringIO(DATA)))
    for row in rows:
        for key in ('outer', 'bore', 'pcd', 'count', 'hole'):
            row[key] = int(row[key])
    return rows


def validate(row):
    D, b, p, n, d = (row[k] for k in ('outer', 'bore', 'pcd', 'count', 'hole'))
    reasons = []
    if min(D, b, p, n, d) <= 0 or b >= D or n < 2:
        return ['尺寸须为正，中心孔须小于外径，孔数须至少为 2'], {}
    outside = (D - p - d) / 2
    inside = (p - b - d) / 2
    adjacent = p * math.sin(math.pi / n)
    if outside <= 0:
        reasons.append(f'螺栓孔超出外圆 {-outside:g} mm' if outside < 0 else '螺栓孔与外圆相切')
    if inside <= 0:
        reasons.append(f'螺栓孔与中心孔相交 {-inside:g} mm' if inside < 0 else '螺栓孔碰到中心孔')
    if adjacent <= d:
        reasons.append(f'相邻螺栓孔中心距 {adjacent:.6f} mm，孔径 {d} mm，重叠 {d-adjacent:.6f} mm'
                       if adjacent < d else '相邻螺栓孔相切')
    return reasons, dict(outer_clearance_mm=outside, bore_clearance_mm=inside,
                         adjacent_center_distance_mm=adjacent, adjacent_clearance_mm=adjacent-d)


def make_dxf(row):
    doc = ezdxf.new('R2010', setup=True)
    doc.units = units.MM
    doc.header['$MEASUREMENT'] = 1
    doc.header['$LTSCALE'] = 1.0
    doc.header['$LWDISPLAY'] = True
    # An explicit millimetre dash-dot pattern: long dash, gap, dot, gap.
    if 'CENTER' in doc.linetypes:
        doc.linetypes.remove('CENTER')
    doc.linetypes.new('CENTER', dxfattribs={
        'description': 'Center ____ . ____ . ____',
        'pattern': [14.0, 10.0, -1.5, 1.0, -1.5],
    })
    for name, weight, ltype in (
        ('OUTLINE', 35, 'CONTINUOUS'), ('BORE', 35, 'CONTINUOUS'),
        ('BOLT_HOLES', 35, 'CONTINUOUS'), ('PCD', 18, 'CENTER'),
        ('CENTERLINES', 18, 'CENTER'), ('DIMENSIONS', 18, 'CONTINUOUS'),
        ('TITLE', 25, 'CONTINUOUS'),
    ):
        doc.layers.new(name, dxfattribs={'color': 7, 'lineweight': weight, 'linetype': ltype})
    doc.styles.new('FLANGE_TEXT', dxfattribs={'font': 'msyh.ttc'})
    doc.dimstyles.new('FLANGE_MM', dxfattribs={
        'dimtxsty': 'FLANGE_TEXT', 'dimtxt': 3.5, 'dimasz': 2.5,
        'dimgap': 1.0, 'dimdec': 0, 'dimtad': 1, 'dimtih': 1,
        'dimtoh': 1, 'dimclrd': 0, 'dimclre': 0, 'dimclrt': 0,
        'dimlunit': 2, 'dimlfac': 1.0, 'dimzin': 8,
    })
    msp = doc.modelspace()
    R, r, P = row['outer']/2, row['bore']/2, row['pcd']/2
    for radius, layer in ((R, 'OUTLINE'), (r, 'BORE'), (P, 'PCD')):
        msp.add_circle((0, 0), radius, dxfattribs={'layer': layer})
    centers = []
    for i in range(row['count']):
        theta = math.pi/2 - 2*math.pi*i/row['count']
        c = (P*math.cos(theta), P*math.sin(theta))
        centers.append(c)
        msp.add_circle(c, row['hole']/2, dxfattribs={'layer': 'BOLT_HOLES'})
    L = R + 8
    msp.add_line((-L, 0), (L, 0), dxfattribs={'layer': 'CENTERLINES'})
    msp.add_line((0, -L), (0, L), dxfattribs={'layer': 'CENTERLINES'})

    # Native diameter DIMENSIONs, each with its own rendered anonymous block.
    # Fixed horizontal text, placed outside the flange in separate quadrants.
    dims = [
        ((0, 0), R, (-R-28, R*.72), f"Ø{row['outer']}"),
        ((0, 0), r, (-R-28, -R*.60), f"Ø{row['bore']}"),
        ((0, 0), P, (R+28, -R*.67), f"PCD Ø{row['pcd']}"),
        (centers[1], row['hole']/2, (R+28, R*.75), f"{row['count']}×Ø{row['hole']}"),
    ]
    for center, radius, location, text in dims:
        dim = msp.add_diameter_dim(center=center, radius=radius, location=location,
                                   text=text, dimstyle='FLANGE_MM',
                                   dxfattribs={'layer': 'DIMENSIONS'})
        dim.render()
    title = f"{row['part']}  材料 {row['material']}"
    msp.add_mtext(title, dxfattribs={'layer': 'TITLE', 'style': 'FLANGE_TEXT',
                  'char_height': 4, 'insert': (0, -R-22, 0), 'attachment_point': 2})
    doc.set_modelspace_vport(height=2*R+90, center=(0, -5))
    path = ROOT / f"{row['part']}.dxf"
    doc.saveas(path)
    return path


def near(a, b, tol=1e-7):
    assert abs(a-b) < tol, (a, b)


def verify_dxf(row, path):
    # Reopen serialized files and check actual entity geometry, not creation lists.
    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    assert not auditor.errors and not auditor.fixes, (path.name, auditor.errors, auditor.fixes)
    assert doc.units == units.MM
    msp = doc.modelspace()
    assert len(msp.query('CIRCLE')) == row['count']+3
    for layer, diameter in [('OUTLINE', row['outer']), ('BORE', row['bore']), ('PCD', row['pcd'])]:
        circle, = list(msp.query(f'CIRCLE[layer=="{layer}"]'))
        near(circle.dxf.center.magnitude, 0)
        near(circle.dxf.radius*2, diameter)
    assert doc.layers.get('PCD').dxf.linetype == 'CENTER'
    assert doc.layers.get('CENTERLINES').dxf.linetype == 'CENTER'
    assert 'CENTER' in doc.linetypes
    bolts = list(msp.query('CIRCLE[layer=="BOLT_HOLES"]'))
    assert len(bolts) == row['count']
    near(bolts[0].dxf.center.x, 0)
    near(bolts[0].dxf.center.y, row['pcd']/2)
    angles = sorted(math.atan2(c.dxf.center.y, c.dxf.center.x) % (2*math.pi) for c in bolts)
    for i, angle in enumerate(angles):
        gap = (angles[(i+1) % len(angles)]-angle) % (2*math.pi)
        near(gap, 2*math.pi/row['count'])
    pair_clearance = float('inf')
    for i, c in enumerate(bolts):
        near(c.dxf.radius*2, row['hole'])
        near(c.dxf.center.magnitude, row['pcd']/2)
        assert c.dxf.center.magnitude+c.dxf.radius < row['outer']/2
        assert c.dxf.center.magnitude-c.dxf.radius > row['bore']/2
        for other in bolts[i+1:]:
            clear = c.dxf.center.distance(other.dxf.center)-c.dxf.radius-other.dxf.radius
            assert clear > 0
            pair_clearance = min(pair_clearance, clear)
    lines = list(msp.query('LINE[layer=="CENTERLINES"]'))
    assert len(lines) == 2
    L = row['outer']/2+8
    expected = [((-L, 0, 0), (L, 0, 0)), ((0, -L, 0), (0, L, 0))]
    for line, (start, end) in zip(lines, expected):
        near(line.dxf.start.distance(Vec3(start)), 0)
        near(line.dxf.end.distance(Vec3(end)), 0)
    dims = list(msp.query('DIMENSION'))
    assert len(dims) == 4
    expected_text = [f"Ø{row['outer']}", f"Ø{row['bore']}", f"PCD Ø{row['pcd']}",
                     f"{row['count']}×Ø{row['hole']}"]
    for dim, text, diameter, center in zip(dims, expected_text,
            [row['outer'], row['bore'], row['pcd'], row['hole']],
            [Vec3(), Vec3(), Vec3(), bolts[1].dxf.center]):
        assert dim.dimtype == 3
        assert dim.dxf.text == text
        near(dim.get_measurement(), diameter)
        near(((dim.dxf.defpoint+dim.dxf.defpoint4)/2).distance(center), 0)
        block = doc.blocks.get(dim.dxf.geometry)
        assert len(block) > 0
        rendered_text = list(block.query('MTEXT'))
        assert len(rendered_text) == 1
        assert rendered_text[0].plain_text() == text
    title, = list(msp.query('MTEXT[layer=="TITLE"]'))
    assert title.plain_text() == f"{row['part']}  材料 {row['material']}"
    assert title.dxf.insert.y < -row['outer']/2-10
    return {'file': path.name, 'audit_errors': 0, 'audit_fixes': 0,
            'circle_count': len(msp.query('CIRCLE')), 'bolt_count': len(bolts),
            'dimension_count': len(dims), 'dimension_texts': expected_text,
            'first_bolt_center_mm': [round(bolts[0].dxf.center.x, 8), bolts[0].dxf.center.y],
            'minimum_pair_clearance_mm': pair_clearance}


def make_preview(path):
    """Dependency-free SVG of reread DXF and rendered dimension blocks."""
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    ext = bbox.extents(msp, fast=True)
    x0, y0 = ext.extmin.x-8, ext.extmin.y-8
    w, h = ext.size.x+16, ext.size.y+16
    ns = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', ns)
    root = ET.Element(f'{{{ns}}}svg', {'viewBox': f'{x0} {-y0-h} {w} {h}',
                    'width': '1000', 'height': str(round(1000*h/w))})
    ET.SubElement(root, 'rect', {'x': str(x0), 'y': str(-y0-h), 'width': str(w),
                                'height': str(h), 'fill': 'white'})

    def draw(entity, inherited='0'):
        kind = entity.dxftype()
        layer = entity.dxf.layer if entity.dxf.layer != '0' else inherited
        attr = {'stroke': '#111', 'fill': 'none', 'stroke-width': '.22'}
        if layer in ('PCD', 'CENTERLINES'):
            attr.update({'stroke': '#777', 'stroke-dasharray': '10 1.5 1 1.5', 'stroke-width': '.18'})
        elif layer in ('OUTLINE', 'BORE', 'BOLT_HOLES'):
            attr['stroke-width'] = '.35'
        if kind == 'CIRCLE':
            c = entity.dxf.center
            ET.SubElement(root, 'circle', dict(attr, cx=str(c.x), cy=str(-c.y), r=str(entity.dxf.radius)))
        elif kind == 'LINE':
            a, b = entity.dxf.start, entity.dxf.end
            ET.SubElement(root, 'line', dict(attr, x1=str(a.x), y1=str(-a.y), x2=str(b.x), y2=str(-b.y)))
        elif kind == 'SOLID':
            pts = list(entity.vertices())
            ET.SubElement(root, 'polygon', dict(attr, points=' '.join(f'{p.x},{-p.y}' for p in pts), fill='#111'))
        elif kind in ('DIMENSION', 'INSERT'):
            for child in entity.virtual_entities():
                draw(child, layer)
        elif kind == 'MTEXT':
            p = entity.dxf.insert
            attach = entity.dxf.attachment_point
            anchor = {0: 'end', 1: 'start', 2: 'middle'}[attach % 3]
            baseline = 'hanging' if attach <= 3 else ('central' if attach <= 6 else 'auto')
            rotation = entity.dxf.get('rotation', 0)
            if entity.dxf.hasattr('text_direction'):
                v = entity.dxf.text_direction
                rotation = math.degrees(math.atan2(v.y, v.x))
            attrs = {'x': str(p.x), 'y': str(-p.y), 'font-size': str(entity.dxf.char_height),
                     'font-family': 'Microsoft YaHei,Arial,sans-serif', 'fill': '#111',
                     'text-anchor': anchor, 'dominant-baseline': baseline}
            if rotation:
                attrs['transform'] = f'rotate({-rotation} {p.x} {-p.y})'
            text = ET.SubElement(root, 'text', attrs)
            text.text = entity.plain_text()
        elif kind == 'POINT':
            pass  # dimension definition points are not plotted
        else:
            raise AssertionError(f'Preview unsupported entity: {kind}')

    for entity in msp:
        draw(entity)
    svg_path = path.with_suffix('.svg')
    ET.ElementTree(root).write(svg_path, encoding='utf-8', xml_declaration=True)
    return svg_path.name


def main():
    results = {'units': 'mm', 'ezdxf_version': ezdxf.__version__, 'generated': [], 'rejected': []}
    for row in read_rows():
        reasons, clearance = validate(row)
        if reasons:
            assert not (ROOT / f"{row['part']}.dxf").exists(), 'Rejected part already has a DXF'
            results['rejected'].append(dict(part=row['part'], reasons=reasons, **clearance))
            continue
        path = make_dxf(row)
        checked = verify_dxf(row, path)
        checked.update(clearance)
        checked['preview'] = make_preview(path)
        results['generated'].append(checked)
    assert len(results['generated']) == 10
    assert {r['part'] for r in results['rejected']} == {'FL-109', 'FL-111'}
    (ROOT / 'verification_report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 法兰盘批量出图核对报告', '', '单位：mm；DXF R2010；ezdxf '+ezdxf.__version__, '',
             '成功生成并回读核对 10 张 DXF，每张含外圆、中心孔、节圆、均布螺栓孔、两条中心线、4 个原生直径标注及零件材料标题。',
             '孔位从正上方起按顺时针均布。节圆及中心线使用 CENTER 点画线。',
             'PCD 表示节圆直径。所有标注均渲染为 DXF 图块。所有文件 audit 错误和修复均为 0。', '',
             '| 零件 | 外圆边距 | 中心孔边距 | 相邻孔中心距 | 相邻孔净距 |',
             '|---|---:|---:|---:|---:|']
    for entry in results['generated']:
        lines.append(f"| {Path(entry['file']).stem} | {entry['outer_clearance_mm']:.3f} | {entry['bore_clearance_mm']:.3f} | {entry['adjacent_center_distance_mm']:.3f} | {entry['adjacent_clearance_mm']:.3f} |")
    lines += ['', '未出图：']
    for entry in results['rejected']:
        lines.append(f"- {entry['part']}：{'；'.join(entry['reasons'])}。")
    lines += ['', '运行中发现 ezdxf 绘图预览模块依赖未安装的 Pillow；未安装任何新包，改用标准库生成 SVG 预览。',
              '另一次 API 探查遇到不存在的内部类名；改用公开 add_diameter_dim API 生成原生标注。',
              '中文文字使用 Microsoft YaHei 字体引用，DXF 不嵌入字体，其他计算机需安装兼容中文字库。',
              'SVG 为辅助预览；最终尺寸以 DXF 实体及回读核对为准。本次未在 CAD 软件中打开或进行打印验证。',
              '未添加图框、剖视图或加工公差（任务未要求）。']
    (ROOT / '核对报告.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    links = '\n'.join(f'<li><a href="{r["preview"]}">{r["file"]}</a></li>' for r in results['generated'])
    (ROOT / '预览索引.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>法兰盘预览</title><body><h1>法兰盘主视图</h1><p>单位 mm；点击查看 SVG 辅助预览，同名 DXF 为正式图纸。</p><ul>'+links+'</ul></body></html>', encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
