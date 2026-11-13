"""Optional SuperMap-compatible exports; never invoked by the default modelling workflow."""
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import bpy


def plain(v):
    if isinstance(v,(str,int,float,bool)) or v is None:
        return v
    if hasattr(v,'to_dict'):
        return {k:plain(x) for k,x in v.to_dict().items()}
    return [plain(x) for x in v]


def export(config):
    import zipfile
    out=Path(config['output'])
    target=out/'supermap'
    target.mkdir(exist_ok=True)
    origin=list(bpy.context.scene['Project.Origin_E_N_H'])
    objects=[o for o in bpy.context.scene.objects if o.type in ('MESH','CURVE','FONT')]
    for o in bpy.context.scene.objects:
        o.hide_set(False)
        o.select_set(o in objects)
    bpy.context.view_layer.objects.active=objects[0]
    for o in objects:
        o['ExportId']=o.get('IFC.GlobalId') or hashlib.sha256((bpy.context.scene['Project.Name']+o.name).encode()).hexdigest()[:22]
    bpy.ops.object.convert(target='MESH')
    objects=sorted(bpy.context.selected_objects,key=lambda o:o.name)
    metadata=[]
    for o in objects:
        o.data.calc_loop_triangles()
        metadata.append(dict(object=o.name,properties={k:plain(o[k]) for k in o.keys()},triangles=len(o.data.loop_triangles)))
    for m in bpy.data.materials:
        color=list(m.diffuse_color)
        m.use_nodes=True
        bsdf=m.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value=color
            bsdf.inputs['Metallic'].default_value=0
            bsdf.inputs['Roughness'].default_value=.85
        m.use_backface_culling=False
    bpy.ops.wm.obj_export(filepath=str(target/'model.obj'),export_selected_objects=True,forward_axis='Y',up_axis='Z',
                          export_materials=True,export_object_groups=True,export_triangulated_mesh=True)
    names=sorted((o.name for o in objects),key=len,reverse=True)
    seen=set()
    lines=[]
    for line in (target/'model.obj').read_text(encoding='utf-8').splitlines(keepends=True):
        if line.startswith('g '):
            raw=line[2:].strip()
            name=next((n for n in names if raw==n or raw.startswith(n+'_')),None)
            if name is None or name in seen:
                raise ValueError('OBJ object-name mapping failed')
            seen.add(name)
            lines.extend(['o '+name+'\n','g '+name+'\n'])
        else:
            lines.append(line)
    if seen!=set(names):
        raise ValueError('OBJ lost model objects')
    (target/'model.obj').write_text(''.join(lines),encoding='utf-8')
    bpy.ops.export_scene.gltf(filepath=str(target/'model.gltf'),export_format='GLTF_SEPARATE',use_selection=True,
                              export_extras=True,export_yup=True,export_cameras=False,export_lights=False,export_animations=False)
    (target/'properties.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    with (target/'properties.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f)
        writer.writerow(['ObjectName','ExportId','IFCClass','GlobalId','PropertiesJSON'])
        for row in metadata:
            p=row['properties']
            writer.writerow([row['object'],p['ExportId'],p.get('IFC.Class',''),p.get('IFC.GlobalId',''),json.dumps(p,ensure_ascii=False)])
    (target/'placement.json').write_text(json.dumps(dict(unit='m',obj_axes='X east, Y north, Z up; no rotation',
        gltf_axes='standard glTF Y-up; X east,Y elevation,Z negative north',origin_E_N_H=origin,
        horizontal_crs='UNKNOWN',vertical_datum='UNKNOWN'),indent=2),encoding='utf-8')
    shutil.copyfile(out/'quality_report.json',target/'quality_report.json')
    reference=Path(__file__).resolve().parents[1]/'references'/'supermap.md'
    shutil.copyfile(reference,target/'导入说明.md')
    gltf=json.loads((target/'model.gltf').read_text(encoding='utf-8'))
    nodes={n['name']:n for n in gltf['nodes'] if 'mesh' in n}
    if set(nodes)!=set(names):
        raise ValueError('glTF lost model objects')
    for row in metadata:
        node=nodes[row['object']]
        if node['extras']['ExportId']!=row['properties']['ExportId']:
            raise ValueError('glTF lost export identity')
        for key,value in row['properties'].items():
            if node['extras'].get(key)!=value:
                raise ValueError('glTF property mismatch: '+key)
        count=sum(gltf['accessors'][p['indices']]['count']//3 for p in gltf['meshes'][node['mesh']]['primitives'])
        if count!=row['triangles']:
            raise ValueError('glTF triangle count mismatch')
    for b in gltf['buffers']:
        if (target/b['uri']).stat().st_size!=b['byteLength']:
            raise ValueError('glTF buffer length mismatch')
    (target/'export_validation.json').write_text(json.dumps(dict(objects=len(objects),triangles=sum(o['triangles'] for o in metadata),
        gltf_properties_verified=True,supermap_import_tested=False),indent=2),encoding='utf-8')
    archive=Path(shutil.make_archive(str(out/'supermap'),'zip',target))
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('Export archive failed CRC check')
    print('SUPERMAP_EXPORTED',archive)


if __name__=='__main__':
    export(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8')))
