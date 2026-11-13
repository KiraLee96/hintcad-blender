"""Reopen-file validation independent of in-memory building state."""
import json
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hintcad import Project


def verify(config):
    out=Path(config['output'])
    quality=json.loads((out/'quality_report.json').read_text(encoding='utf-8'))
    p=Project(config['input'],config['stage'],config.get('project'),config.get('start'),config.get('end'))
    current=p.inspect()
    if quality['files']!=current['files']:
        raise ValueError('Inputs changed during generation')
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if len(meshes)!=quality['surface_object_count']:
        raise ValueError('Persisted mesh count differs')
    triangles=0
    for obj in meshes:
        mesh=obj.data
        used={tuple(sorted(edge)) for face in mesh.polygons for edge in face.edge_keys}
        if any(tuple(sorted(edge.vertices)) not in used for edge in mesh.edges):
            raise ValueError('Loose wire edges: '+obj.name)
        if any(not all(math.isfinite(x) for x in v.co) for v in mesh.vertices):
            raise ValueError('Non-finite vertex: '+obj.name)
        if any(f.area<=0 for f in mesh.polygons):
            raise ValueError('Zero-area face: '+obj.name)
        triangles+=len(mesh.polygons)
        layers={c.name for c in obj.users_collection}
        if p.stage=='full' and layers & {'Earthworks','Drainage','Transitions'}:
            side=obj['Project_LinearReference.Side']
            values=mesh.attributes['station_offset_m'].data
            for face in mesh.polygons:
                ss=[p.start+values[i].value for i in face.vertices]
                if max(ss)-min(ss)>max(config['step'],.25)+.002:
                    raise ValueError('Unexpected longitudinal mesh leap')
                if any(min(ss)<r['end']-.001 and max(ss)>r['start']+.001 for r in quality['excluded'][side]):
                    raise ValueError('Saved face crosses bridge/tunnel exclusion')
    ids=[o['IFC.GlobalId'] for o in bpy.context.scene.objects if 'IFC.GlobalId' in o]
    if len(ids)!=len(set(ids)) or len(ids)!=quality['ifc_mapped_objects']:
        raise ValueError('Invalid or duplicate object identities')
    if triangles!=quality['triangle_count']:
        raise ValueError('Persisted triangle count differs')
    result=dict(status='verified',surface_objects=len(meshes),triangles=triangles,identities=len(ids),
                no_loose_edges=True,bridge_tunnel_exclusions_verified=p.stage=='full',
                input_hashes_verified=True,unresolved_profiles=len(quality['unresolved_profiles']),
                transition_count=quality['transition_count'],
                limitations=['Interpolated ground, not additional survey','Surface geometry, not soil volumes',
                             'Transitions are geometric assumptions, not hydraulic or construction design',
                             'IFC naming is Blender metadata, not native IFC entities'])
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    verify(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8')))
