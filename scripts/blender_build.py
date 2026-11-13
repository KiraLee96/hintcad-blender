"""Blender backend for the reusable HintCAD skill. Receives a JSON request after --."""
import csv
import json
import math
import sys
import uuid
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hintcad import Project
from physics import calculate, outside_window
from geometry import elevation, station_label


def identifier(namespace,name):
    v=uuid.uuid5(uuid.NAMESPACE_URL,namespace+':'+name).int
    alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$'
    return ''.join(alphabet[(v>>(6*i))&63] for i in reversed(range(22)))


def build(config):
    if not bpy.app.background:
        raise RuntimeError('Use the runner to create a separate background Blender process')
    p=Project(config['input'],config['stage'],config.get('project'),config.get('start'),config.get('end'))
    out=Path(config['output'])
    if out.resolve().is_relative_to(p.folder):
        raise ValueError('Output must be outside the source data directory')
    out.mkdir(parents=True,exist_ok=True)
    model=calculate(p,config['step'],config['transition_length'])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene
    scene.unit_settings.system='METRIC'
    scene['Project.Name']=p.name
    scene['Project.Origin_E_N_H']=p.origin
    scene['Project.Range']=[p.start,p.end]
    scene['IFC.TargetSchema']='IFC4X3_ADD2'
    scene['IFC.MetadataMode']='Blender custom properties only; no native IFC entities exported'
    namespace=p.settings.get('214') or str(uuid.uuid5(uuid.NAMESPACE_URL,p.name+':'+p.files['pm'].read_text(encoding='gb18030',errors='replace')))
    collections={}
    for name in ('Route','Pavement','Earthworks','Drainage','Daylight','Transitions','StationLabels'):
        c=bpy.data.collections.new(name)
        scene.collection.children.link(c)
        collections[name]=c
    mats={}
    for name,color in dict(ROUTE=(1,.015,.015,1),MEDIAN=(.055,.48,.075,1),LANE=(.13,.18,.23,1),
                           HARD=(.4,.45,.49,1),SOIL=(.055,.48,.075,1),FILL=(.2,.36,.105,1),
                           CUT=(.48,.3,.16,1),BENCH=(.12,.26,.07,1),BERM=(.16,.30,.08,1),
                           WATER=(.48,.52,.55,1),DAYLIGHT=(.95,.65,.08,1),LIMIT=(1,.015,.015,1),TEXT=(.95,.95,.95,1)).items():
        mat=bpy.data.materials.new(name)
        mat.diffuse_color=color
        mats[name]=mat
    source=';'.join(f.name for f in p.files.values())
    objects=[]
    triangles=0

    def props(obj,cls,title,predefined='NOTDEFINED',**extra):
        obj['IFC.Class']=cls
        obj['IFC.Schema']='IFC4X3_ADD2'
        obj['IFC.Name']=title
        obj['IFC.GlobalId']=identifier(namespace,obj.name)
        obj['IFC.PredefinedType']=predefined
        obj['Project_Source.Files']=source
        obj['Project_Georeference.Origin_E_N_H']=p.origin
        obj['Project_Georeference.Status']='Coordinate system and vertical datum not confirmed'
        for key,value in extra.items():
            obj[key]=value

    def ribbon(name,side,records,roles,layer,metadata,excluded=None,clip=True):
        nonlocal triangles
        # records: station and a shared ordered cross-section; edges are derived exclusively from faces.
        count=len(records[0][1])
        vertices=[p.world(s,side,point) for s,points in records for point in points]
        faces=[]
        material_roles=[]
        cells=[]
        for i in range(len(records)-1):
            a_s,b_s=records[i][0],records[i+1][0]
            if clip and not outside_window(a_s,b_s,side,model['windows']):
                continue
            if excluded and any(a_s<e['end']-1e-7 and b_s>e['start']+1e-7 for e in excluded):
                raise ValueError('Mesh face overlaps an excluded structure')
            used=False
            for j,role in enumerate(roles):
                if role is None:
                    continue
                a,b,c,d=count*i+j,count*i+j+1,count*(i+1)+j,count*(i+1)+j+1
                tris=[(a,c,d),(a,d,b)] if side=='LEFT' else [(a,b,d),(a,d,c)]
                for tri in tris:
                    normal=(Vector(vertices[tri[1]])-Vector(vertices[tri[0]])).cross(Vector(vertices[tri[2]])-Vector(vertices[tri[0]]))
                    if normal.length_squared<1e-14:
                        continue
                    faces.append(tuple(reversed(tri)) if normal.z<0 else tri)
                    material_roles.append(role)
                    used=True
            if used:
                cells.append((i,a_s,b_s))
        if not faces:
            return None
        mesh=bpy.data.meshes.new(name)
        mesh.from_pydata(vertices,[],faces)
        if mesh.validate():
            raise ValueError('Mesh required unexpected repair: '+name)
        mesh.update()
        if any(f.area<=0 for f in mesh.polygons):
            raise ValueError('Degenerate mesh face: '+name)
        unique=list(dict.fromkeys(material_roles))
        for role in unique:
            mesh.materials.append(mats[role])
        for face,role in zip(mesh.polygons,material_roles):
            face.material_index=unique.index(role)
        attr=mesh.attributes.new('station_offset_m','FLOAT','POINT')
        for item,value in zip(attr.data,[s-p.start for s,points in records for _ in points]):
            item.value=value
        obj=bpy.data.objects.new(name,mesh)
        collections[layer].objects.link(obj)
        cls=metadata.pop('class')
        title=metadata.pop('title')
        predefined=metadata.pop('predefined','NOTDEFINED')
        props(obj,cls,title,predefined,**metadata)
        obj['Project_LinearReference.Side']=side
        obj['Project_LinearReference.StartStation']=min(a for _,a,b in cells)
        obj['Project_LinearReference.EndStation']=max(b for _,a,b in cells)
        obj['Project_Geometry.SurfaceArea']=sum(f.area for f in mesh.polygons)
        obj['Project_Geometry.SurfaceOnly']=True
        if cls in ('IfcEarthworksFill','IfcEarthworksCut','IfcPavement') and count==2:
            length=sum((Vector(vertices[count*(i+1)])+Vector(vertices[count*(i+1)+1])-
                        Vector(vertices[count*i])-Vector(vertices[count*i+1])).length/2 for i,a,b in cells)
            qto={'IfcEarthworksFill':'Qto_EarthworksFillBaseQuantities','IfcEarthworksCut':'Qto_EarthworksCutBaseQuantities','IfcPavement':'Qto_PavementBaseQuantities'}[cls]
            obj[qto+'.Length']=length
        objects.append(obj)
        triangles+=len(faces)
        return obj

    def line(name,points,role,side=None,semantic=None):
        if len(points)<2:
            return None
        data=bpy.data.curves.new(name,'CURVE')
        data.dimensions='3D'
        data.bevel_depth=.25 if role in ('ROUTE','LIMIT') else .12
        data.bevel_resolution=2
        data.materials.append(mats[role])
        spline=data.splines.new('POLY')
        spline.points.add(len(points)-1)
        for item,(_,xyz) in zip(spline.points,points):
            item.co=(*xyz,1)
        obj=bpy.data.objects.new(name,data)
        collections['Route' if role=='ROUTE' else 'Daylight'].objects.link(obj)
        obj['Project_Geometry.Role']=semantic or role
        obj['Project_LinearReference.StartStation']=points[0][0]
        obj['Project_LinearReference.EndStation']=points[-1][0]
        if side:
            obj['Project_LinearReference.Side']=side
        return obj

    route_points=[(s,p.world(s,'RIGHT',(0,elevation(p.vpis,s)))) for s in model['road_stations']]
    route=line(p.slug+'_ALIGNMENT',route_points,'ROUTE')
    props(route,'IfcAlignment',p.name+'路线')
    route['Project_Alignment.HorizontalLength']=p.end-p.start
    route['Project_Alignment.HorizontalSegmentCount']=len(p.segments)
    route['Project_Source.PM']=str(p.files['pm'])
    route['Project_Source.ZDM']=str(p.files['zdm'])
    if p.stage!='route':
        for side in ('LEFT','RIGHT'):
            sections=[]
            width_values=[]
            for s in model['road_stations']:
                points,widths,grades=p.section(s,side)
                sections.append((s,[(0,elevation(p.vpis,s))]+points))
                width_values.append(widths)
            for band,(name,role) in enumerate(zip(('Median','Carriageway','HardShoulder','EarthShoulder'),('MEDIAN','LANE','HARD','SOIL'))):
                pavement=band in (1,2)
                metadata={'class':'IfcPavement' if pavement else 'IfcGeographicElement','title':p.name+' '+side+' '+name,
                          'predefined':'NOTDEFINED' if pavement else 'USERDEFINED'}
                if not pavement:
                    metadata['IFC.ObjectType']='MEDIAN_SURFACE' if band==0 else 'EARTH_SHOULDER_SURFACE'
                values=[w[band] for w in width_values]
                metadata['Project_Geometry.WidthMin']=min(values)
                metadata['Project_Geometry.WidthMax']=max(values)
                if pavement:
                    if max(values)-min(values)<1e-6:
                        metadata['Pset_PavementCommon.NominalWidth']=values[0]
                    metadata['Pset_PavementCommon.NominalLength']=p.end-p.start
                    metadata['Project_DataQuality.Missing']='Thickness, pavement structural type, material, IRI and texture are not supplied'
                ribbon(f'{p.slug}_{side}_{name}',side,[(s,points[band:band+2]) for s,points in sections],[role],
                       'Pavement',metadata,clip=False)
    for index,run in enumerate(model['runs']):
        keys=sorted({k for row in run['profiles'] for k in row['bands']})
        for key in keys:
            records=[]
            actual=[]
            for row in run['profiles']:
                feature=row['bands'].get(key)
                records.append((row['station'],[feature['a'],feature['b']] if feature else [row['terminal']]*2))
                if feature:
                    actual.append(feature)
            feature=actual[0]
            water=feature['role']=='WATER'
            berm=feature['role']=='BERM'
            cls='IfcEarthworksCut' if water or run['mode']=='CUT' else 'IfcEarthworksFill'
            metadata={'class':cls,'title':f'{p.name} {run["side"]} {run["mode"]} {key}',
                      'predefined':'TRENCH' if water else ('CUT' if run['mode']=='CUT' else 'SLOPEFILL'),
                      'Project_Slope.Mode':run['mode'],'Project_Slope.Feature':key,
                      'Project_Slope.SignedRatio1ToM':feature['ratio'],'Project_Slope.LiningFlag':feature['lining'],
                      'Project_Source.CTRRecord':' '.join(run['ditch_row'] if key.startswith(('DRAIN','DITCH')) else run['slope_row']),
                      'Project_DataQuality.DaylightStatus':'UNRESOLVED_PRESENT' if any(r['contact'] is None for r in run['profiles']) else 'DAYLIGHTED'}
            ribbon(f'{p.slug}_{run["side"]}_{run["mode"]}_{index}_{key}',run['side'],records,[feature['role']],
                   'Drainage' if water or berm else 'Earthworks',metadata,run['excluded'])
        for valid,role in ((True,'DAYLIGHT'),(False,'LIMIT')):
            chain=[]
            part=0
            for row in run['profiles']+[None]:
                s=row['station'] if row else None
                inside=row and any(w['side']==run['side'] and w['start']<s<w['end'] for w in model['windows'])
                if row and (row['contact'] is not None)==valid and not inside:
                    chain.append((s,p.world(s,run['side'],row['terminal'])))
                else:
                    line(f'{p.slug}_{run["side"]}_{index}_{role}_{part}',chain,role,run['side'],
                         '真实坡脚线' if valid and run['mode']=='FILL' else '真实坡口线' if valid else '未交地测量边界，不是坡脚')
                    chain=[]
                    part+=1
    for i,tr in enumerate(model['transitions']):
        records=[(r['station'],r['points']) for r in tr['samples']]
        for kind in ('EARTHWORKS','DITCH'):
            roles=[role if (role=='WATER')==(kind=='DITCH') else None for role in tr['roles']]
            metadata={'class':'IfcEarthworksCut' if kind=='DITCH' else 'IfcGeographicElement','title':p.name+'填挖渐变'+kind,
                      'predefined':'TRENCH' if kind=='DITCH' else 'USERDEFINED',
                      'Project_Transition.RootStation':tr['root'],'Project_Transition.AssumedLength':tr['end']-tr['start'],
                      'Project_Transition.Status':'Geometric interpolation only; recheck terrain ties, longitudinal drainage and construction design'}
            if kind=='EARTHWORKS':
                metadata['IFC.ObjectType']='CUT_FILL_GEOMETRIC_TRANSITION'
            ribbon(f'{p.slug}_{tr["side"]}_TRANSITION_{i}_{kind}',tr['side'],records,roles,'Transitions',metadata,clip=False)
    labels={p.start,p.end}|{s for s in range(math.ceil(p.start/config['label_interval'])*config['label_interval'],math.floor(p.end/config['label_interval'])*config['label_interval']+1,config['label_interval'])
                          if min(s-p.start,p.end-s)>=.6*config['label_interval']}
    for s in sorted(labels):
        n,e,theta=p.frame(s)
        z=elevation(p.vpis,s)
        data=bpy.data.curves.new(station_label(s),'FONT')
        data.body=station_label(s)
        data.size=min(12,max(2,(p.end-p.start)/30))
        data.align_x='CENTER'
        data.materials.append(mats['TEXT'])
        obj=bpy.data.objects.new(station_label(s),data)
        collections['StationLabels'].objects.link(obj)
        obj.location=(e+20*math.cos(theta)-p.origin[0],n-20*math.sin(theta)-p.origin[1],z-p.origin[2]+.8)
        obj.rotation_euler.z=math.pi/2-theta
        obj.show_in_front=True
        props(obj,'IfcReferent',station_label(s),'STATION',**{'Pset_Stationing.Station':s,'Pset_Stationing.HasIncreasingStation':True})
        line(station_label(s)+'_tick',[(s,p.world(s,'RIGHT',(d,z+.5))) for d in (0,16)],'TEXT')
    ids=[o['IFC.GlobalId'] for o in scene.objects if 'IFC.GlobalId' in o]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate IFC identifiers')
    for obj in objects:
        used={tuple(sorted(e)) for f in obj.data.polygons for e in f.edge_keys}
        if any(tuple(sorted(e.vertices)) not in used for e in obj.data.edges):
            raise ValueError('Loose wire geometry: '+obj.name)
    quality=p.inspect()
    quality.update(unresolved_profiles=model['unresolved'],transition_windows=model['windows'],skipped_transitions=model['skipped_transitions'],
                   run_count=len(model['runs']),transition_count=len(model['transitions']),surface_object_count=len(objects),
                   object_count=len(scene.objects),triangle_count=triangles,ifc_mapped_objects=len(ids),
                   warnings=p.warnings+model['warnings'],schema='IFC4X3_ADD2',native_ifc_export=False,
                   surface_only=True,model_file=str(out/'model.blend'))
    if model['unresolved']:
        quality['warnings'].append('Unresolved ground intersections are shown as red boundaries, not fabricated slope toes')
    quality['status']='generated_with_warnings' if quality['warnings'] else 'generated'
    (out/'quality_report.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata=[dict(object=o.name,properties={k:(list(o[k]) if hasattr(o[k],'to_list') else o[k]) for k in o.keys()})
              for o in scene.objects if 'IFC.GlobalId' in o]
    (out/'properties.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'properties.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f)
        writer.writerow(['ObjectName','Property','Value'])
        for item in metadata:
            for key,value in item['properties'].items():
                writer.writerow([item['object'],key,value])
    text=bpy.data.texts.new('项目质量报告')
    text.write(json.dumps(quality,ensure_ascii=False,indent=2))
    bpy.context.view_layer.update()
    pts=[o.matrix_world@Vector(corner) for o in scene.objects if o.type in ('MESH','CURVE','FONT') for corner in o.bound_box]
    low=Vector(tuple(min(v[i] for v in pts) for i in range(3)))
    high=Vector(tuple(max(v[i] for v in pts) for i in range(3)))
    center=(low+high)/2
    span=max((high-low).length,100)
    camera_data=bpy.data.cameras.new('Overview')
    camera=bpy.data.objects.new('Overview',camera_data)
    scene.collection.objects.link(camera)
    camera.location=center+Vector((.8,-.5,1.3))*span
    camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO'
    camera_data.ortho_scale=span*1.55
    camera_data.clip_end=span*20
    scene.camera=camera
    camera.hide_set(True)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                space=area.spaces.active
                space.region_3d.view_location=center
                space.region_3d.view_distance=span*1.3
                space.region_3d.view_rotation=Vector((.8,-.5,1.3)).to_track_quat('Z','Y')
                space.region_3d.view_perspective='ORTHO'
                space.clip_end=span*20
                space.shading.color_type='MATERIAL'
                space.overlay.show_floor=False
    scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.color_type='MATERIAL'
    scene.display.shading.light='STUDIO'
    scene.display.shading.background_type='WORLD'
    scene.world=bpy.data.worlds.new('Background')
    scene.world.color=(.045,.045,.045)
    scene.render.resolution_x=1400
    scene.render.resolution_y=1000
    scene.render.resolution_percentage=100
    scene.render.filepath=str(out/'preview.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'model.blend'))
    bpy.ops.render.render(write_still=True)
    if model['transitions']:
        tr=model['transitions'][0]
        row=tr['samples'][len(tr['samples'])//2]
        focus=Vector(p.world(row['station'],tr['side'],row['points'][tr['channel_index']]))
    else:
        focus=Vector(route_points[len(route_points)//2][1])
    camera.location=focus+Vector((50,-55,65))
    camera.rotation_euler=(focus-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.ortho_scale=130
    scene.render.filepath=str(out/'detail.png')
    bpy.ops.render.render(write_still=True)
    print('HINTCAD_MODEL_CREATED',p.name,quality['status'],len(objects),'surface objects',len(model['transitions']),'transitions',len(model['unresolved']),'unresolved profiles')


if __name__=='__main__':
    path=Path(sys.argv[sys.argv.index('--')+1])
    build(json.loads(path.read_text(encoding='utf-8')))
