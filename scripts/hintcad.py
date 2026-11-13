"""HintCAD project discovery, validation and engineering data access."""
import bisect
import hashlib
import math
import re
from functools import lru_cache
from pathlib import Path

from geometry import horizontal, elevation, height_at, slope_rule, ditch_rule, excluded_ranges


def read_text(path):
    raw=path.read_bytes()
    encodings=['utf-16'] if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else ['utf-8-sig','gb18030']
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f'Cannot decode {path.name}')


def interpolate(points,station):
    if len(points)<2 or not points[0][0]-1e-7<=station<=points[-1][0]+1e-7:
        raise ValueError(f'Data does not cover station {station}')
    i=min(max(1,bisect.bisect_left(points,station,key=lambda p:p[0])),len(points)-1)
    a,b=points[i-1:i+1]
    return a[1]+(b[1]-a[1])*(station-a[0])/(b[0]-a[0])


def finite(values):
    return all(math.isfinite(v) for v in values)


def increasing(stations,label):
    if len(stations)<2 or any(b<=a for a,b in zip(stations,stations[1:])):
        raise ValueError(label+' stations must increase')


class Project:
    def __init__(self,folder,stage='full',project_file=None,start=None,end=None):
        self.folder=Path(folder).resolve()
        if not self.folder.is_dir():
            raise ValueError('Input must be a directory')
        self.stage=stage
        self.warnings=[]
        files=[p for p in self.folder.iterdir() if p.is_file()]
        prjs=[p for p in files if p.suffix.lower()=='.prj']
        if project_file:
            prj=Path(project_file).resolve()
            if not prj.is_relative_to(self.folder):
                raise ValueError('PRJ must be inside the input directory')
        elif len(prjs)>1:
            raise ValueError('Multiple PRJ files; select one with --project')
        else:
            prj=prjs[0] if prjs else None
        self.prj=prj
        text=read_text(prj) if prj else ''
        if stage!='route':
            for code,prefix in [('312','0|'),('313','244|')]:
                values=[m[1].strip() for line in text.splitlines() if (m:=re.match(r'\s*'+code+r'(?!\d)[^=]*=\s*(.*)',line))]
                if any(not v.startswith(prefix) for v in values):
                    raise ValueError('PRJ contains an unvalidated rotation/transition setting (requires median-edge rotation and linear interpolation)')
        self.settings={}
        for line in text.splitlines():
            m=re.match(r'\s*(\d+)[^=]*=\s*(.*)',line)
            if m:
                self.settings[m[1]]=m[2].strip()
        self.name=self.settings.get('203') or (prj.stem if prj else self.folder.name)
        self.slug=re.sub(r'[^\w.-]+','_',self.name).strip('._') or 'Road'
        references={}
        for line in text.splitlines():
            m=re.search(r'\(\*\.([A-Za-z0-9]+)\)\s*=\s*(.*)',line)
            if m and m[2].strip():
                references[m[1].lower()]=m[2].strip().replace('\\','/')
        required=['pm','zdm']+(['wid','sup'] if stage!='route' else [])+(['dmx','hdm','ctr'] if stage=='full' else [])
        self.files={}
        for ext in required+['lj','3dr']:
            candidates=[p for p in files if p.suffix.lower()=='.'+ext]
            path=None
            if ext in references:
                target=(self.folder/references[ext]).resolve()
                if not target.is_relative_to(self.folder):
                    raise ValueError('External PRJ file reference requires a self-contained dataset: '+references[ext])
                path=next((p for p in candidates if p.name.lower()==target.name.lower()),None)
                if path is None and target.is_file():
                    path=target
            if path is None:
                matching=[p for p in candidates if p.stem.lower()==(prj.stem.lower() if prj else self.slug.lower())]
                if len(matching)==1:
                    path=matching[0]
                elif len(candidates)==1:
                    path=candidates[0]
                elif ext in required:
                    raise ValueError(f'Missing or ambiguous .{ext}: use a PRJ referencing the intended file')
            if path:
                self.files[ext]=path
        if prj:
            self.files['prj']=prj
        self.segments=self.load_pm()
        z=self.rows('zdm')
        self.vpis=[list(map(float,r)) for r in z[2:]]
        if len(self.vpis)!=int(z[1][0]) or any(len(r)!=5 or not finite(r) or r[3:]!=[0,0] for r in self.vpis):
            raise ValueError('Invalid ZDM or unsupported vertical elevation steps')
        increasing([r[0] for r in self.vpis],'ZDM')
        if self.vpis[0][2]!=0 or self.vpis[-1][2]!=0:
            raise ValueError('First and last ZDM curve radii must be zero')
        bounds=[(self.segments[0]['start'],self.segments[-1]['end']),(self.vpis[0][0],self.vpis[-1][0])]
        self.widths={}
        self.slopes={}
        if stage!='route':
            if not self.settings or not self.settings.get('312','').startswith('0|') or not self.settings.get('313','').startswith('244|'):
                raise ValueError('A PRJ declaring median-edge rotation (312=0) and linear super transitions (313=244) is required')
            self.load_widths()
            self.load_sup()
            for side in ('LEFT','RIGHT'):
                pairs=self.widths[side]
                bounds.append((pairs[0][0][0],pairs[-1][1][0]))
                for k in range(3):
                    if any(row[1][k+1]>0 for pair in pairs for row in pair):
                        bounds.append((self.slopes[side][k][0][0],self.slopes[side][k][-1][0]))
        self.terrain=None
        self.controls={}
        if stage=='full':
            self.terrain=Terrain(self)
            bounds.append((self.terrain.stations[0],self.terrain.stations[-1]))
            self.controls=self.load_controls()
            for side,prefix in [('LEFT','Z'),('RIGHT','Y')]:
                for suffix in ('TFBP.DAT','WFBP.DAT','BGXS.DAT','PSGXS.DAT'):
                    key=prefix+suffix
                    if key not in self.controls:
                        raise ValueError('Missing CTR section '+key)
                    ends=[float(r[0]) for r in self.controls[key]]
                    if not ends or any(b<=a for a,b in zip(ends,ends[1:])):
                        raise ValueError('CTR section must cover increasing segment ends: '+key)
                    for row in self.controls[key]:
                        slope_rule(row) if 'FBP' in key else self.validate_ditch(row)
                excluded_ranges(self.controls,0 if side=='LEFT' else 1)
        common_start=max(a for a,b in bounds)
        common_end=min(b for a,b in bounds)
        self.start=common_start if start is None else float(start)
        self.end=common_end if end is None else float(end)
        if not common_start-1e-7<=self.start<self.end<=common_end+1e-7:
            raise ValueError(f'Requested range exceeds common input coverage [{common_start},{common_end}]')
        if stage=='full':
            for key in self.controls:
                if key.endswith(('TFBP.DAT','WFBP.DAT','BGXS.DAT','PSGXS.DAT')):
                    self.control(key,self.end)
        for seg in self.segments:
            seg['endpoint_error']=math.dist(horizontal(seg,seg['end']),seg['xy'][4:6])
        if max(s['endpoint_error'] for s in self.segments)>.001:
            raise ValueError('Computed PM endpoints disagree with stored coordinates by more than 1 mm')
        if self.start!=self.segments[0]['start'] or self.end!=self.segments[-1]['end']:
            self.warnings.append('Model range is the common input coverage, not the entire PM range')
        if '301' in self.settings and '302' in self.settings:
            declared=[float(self.settings['301']),float(self.settings['302'])]
            if max(abs(declared[0]-self.start),abs(declared[1]-self.end))>.01:
                self.warnings.append(f'PRJ declared range {declared} differs from common model range [{self.start},{self.end}]')
        n,e,_=self.frame(self.start)
        self.origin=(e,n,elevation(self.vpis,self.start))
        self.lj_checks=self.check_lj()

    def rows(self,ext):
        lines=[]
        for line in read_text(self.files[ext]).splitlines():
            line=line.split('//',1)[0].strip()
            if line:
                lines.append(line.split())
        if not lines or not lines[0][0].startswith('HINTCAD'):
            raise ValueError('Unrecognized file signature: '+self.files[ext].name)
        return lines

    def load_pm(self):
        pm=self.rows('pm')
        result=[]
        n=int(pm[1][0])
        if len(pm)<3+3*n:
            raise ValueError('PM segment count exceeds available records')
        for i in range(n):
            a,xy,st=[list(map(float,r)) for r in pm[3+3*i:6+3*i]]
            if len(a)!=7 or len(xy)!=8 or len(st)!=4 or not finite(a+xy+st) or int(a[6]) not in (1,3,21,22):
                raise ValueError('Unsupported PM segment type/layout')
            if st[1]<=st[0]:
                raise ValueError('PM chainage discontinuity requires explicit chainage mapping')
            delta=math.atan2(math.sin(st[3]-st[2]),math.cos(st[3]-st[2]))
            sign=-1 if delta<0 else 1
            k0=0 if int(a[6])==1 or a[4]==9999 else sign/a[4]
            k1=0 if int(a[6])==1 or a[5]==9999 else sign/a[5]
            if abs((k0+k1)*(st[1]-st[0])/2-delta)>1e-7:
                raise ValueError('PM bearing/curvature mismatch')
            if result and (abs(result[-1]['end']-st[0])>1e-5 or math.dist(result[-1]['xy'][4:6],xy[:2])>.001):
                raise ValueError('Disconnected PM segments')
            result.append(dict(start=st[0],end=st[1],theta=st[2],k0=k0,k1=k1,xy=xy,type=int(a[6])))
        self.pm_starts=[s['start'] for s in result]
        return result

    def load_widths(self):
        data={'LEFT':[],'RIGHT':[]}
        side=None
        for row in self.rows('wid')[1:]:
            if row[0] in ('[LEFT]','[RIGHT]'):
                side=row[0][1:-1]
                continue
            if side is None or len(row)!=7:
                raise ValueError('Invalid WID row')
            v=list(map(float,row))
            if not finite(v) or v[3]!=0 or v[6]!=0 or min(v[1],v[2],v[4],v[5])<0:
                raise ValueError('Attached lanes / negative widths need a separate validated mapping')
            data[side].append((v[0],[v[1],v[2],v[4],v[5]]))
        for side,records in data.items():
            if not records or len(records)%2:
                raise ValueError('WID requires paired start/end records for '+side)
            pairs=list(zip(records[::2],records[1::2]))
            for a,b in pairs:
                if b[0]<=a[0]:
                    raise ValueError('Invalid WID interval')
            for (a,b),(c,d) in zip(pairs,pairs[1:]):
                if abs(b[0]-c[0])>1e-6 or max(abs(x-y) for x,y in zip(b[1],c[1]))>1e-6:
                    raise ValueError('WID gap or instantaneous cross-section jump needs explicit segmentation')
            self.widths[side]=pairs

    def load_sup(self):
        records=[list(map(float,r)) for r in self.rows('sup')[1:]]
        if any(len(r)!=7 or not finite(r) for r in records):
            raise ValueError('Invalid SUP row')
        increasing([r[3] for r in records],'SUP')
        for side,indices in [('LEFT',(2,1,0)),('RIGHT',(4,5,6))]:
            self.slopes[side]=[]
            for i in indices:
                values=[(r[3],r[i]/100) for r in records if r[i]!=9999]
                if len(values)<2 or any(abs(v)>1 for _,v in values):
                    raise ValueError('Insufficient/invalid SUP channel')
                self.slopes[side].append(values)

    def load_controls(self):
        controls={}
        key=None
        for r in self.rows('ctr')[1:]:
            if len(r)==1 and re.fullmatch(r'[A-Za-z0-9_]+\.DAT',r[0]):
                key=r[0].upper()
                controls[key]=[]
            elif key:
                controls[key].append(r)
            else:
                raise ValueError('CTR data before section keyword')
        return controls

    def validate_ditch(self,row):
        parts=ditch_rule(row)
        if any(p['height']<=0 or p['lining'] not in (0,1) for p in parts):
            raise ValueError('Invalid ditch dimensions or lining flag')
        return parts

    def control(self,key,station):
        for r in self.controls[key]:
            if station<=float(r[0])+1e-7:
                return r
        raise ValueError(f'CTR {key} does not cover station {station}')

    @lru_cache(maxsize=1024)
    def frame(self,station):
        i=min(max(0,bisect.bisect_right(self.pm_starts,station)-1),len(self.segments)-1)
        seg=self.segments[i]
        n,e=horizontal(seg,station)
        d=station-seg['start']
        theta=seg['theta']+seg['k0']*d+(seg['k1']-seg['k0'])*d*d/(2*(seg['end']-seg['start']))
        return n,e,theta

    def section(self,station,side):
        pairs=self.widths[side]
        a,b=next((pair for pair in pairs if pair[0][0]-1e-7<=station<=pair[1][0]+1e-7))
        t=(station-a[0])/(b[0]-a[0])
        widths=[x+(y-x)*t for x,y in zip(a[1],b[1])]
        grades=[interpolate(channel,station) if widths[i+1]>0 else 0 for i,channel in enumerate(self.slopes[side])]
        x,z=widths[0],elevation(self.vpis,station)
        points=[(x,z)]
        for width,grade in zip(widths[1:],grades):
            x+=width
            z+=width*grade
            points.append((x,z))
        return points,widths,grades

    def edge(self,station,side):
        return self.section(station,side)[0][-1]

    def world(self,station,side,point):
        n,e,theta=self.frame(station)
        x=point[0]*(-1 if side=='LEFT' else 1)
        return (e+x*math.cos(theta)-self.origin[0],n-x*math.sin(theta)-self.origin[1],point[1]-self.origin[2])

    def check_lj(self):
        if 'lj' not in self.files:
            self.warnings.append('LJ missing: independent design-height/width/crossfall check unavailable')
            return dict(count=0)
        errors=[]
        widths=[]
        for r in self.rows('lj')[1:]:
            v=list(map(float,r))
            if not self.start<=v[0]<=self.end:
                continue
            if len(v) not in (20,24):
                self.warnings.append('Unrecognized LJ layout; not used as geometry input')
                return dict(count=0)
            errors.append(abs(elevation(self.vpis,v[0])-v[2]))
            if self.stage!='route' and len(v)==24:
                for side,w,h in [('LEFT',[v[7],v[6]+v[5],v[4],v[3]],[v[17],v[16],v[14],v[13]])]:
                    p,actual,_=self.section(v[0],side)
                    widths.extend(abs(a-b) for a,b in zip(actual,w))
                    # New LJ layouts differ on duplicate zero-width positions; compare the outer edge only.
                    widths.append(abs(p[-1][1]-v[2]-h[-1]))
        result=dict(count=len(errors),max_height_error_m=max(errors,default=0),max_width_or_outer_height_error_m=max(widths,default=0),
                    scope='Design height; confirmed left-side fields for 24-column LJ. Right-side layout not inferred')
        if result['max_height_error_m']>.005 or result['max_width_or_outer_height_error_m']>.005:
            self.warnings.append('LJ differs from current input parameters; inspect lj_checks before construction use')
        return result

    def inspect(self):
        return dict(project=self.name,slug=self.slug,stage=self.stage,start=self.start,end=self.end,
                    origin_E_N_H=self.origin,pm_segment_count=len(self.segments),
                    max_pm_endpoint_error_m=max(s['endpoint_error'] for s in self.segments),lj_checks=self.lj_checks,
                    warnings=self.warnings,files={k:dict(path=str(v),sha256=hashlib.sha256(v.read_bytes()).hexdigest()) for k,v in self.files.items()},
                    excluded={side:excluded_ranges(self.controls,i) for i,side in enumerate(('LEFT','RIGHT'))} if self.stage=='full' else {})


class Terrain:
    def __init__(self,project):
        dmx=[list(map(float,r)) for r in project.rows('dmx')[1:]]
        if any(len(r)!=2 or not finite(r) for r in dmx):
            raise ValueError('Invalid DMX record')
        increasing([r[0] for r in dmx],'DMX')
        rows=project.rows('hdm')[1:]
        if len(rows)%3:
            raise ValueError('Incomplete HDM block')
        self.stations=[]
        self.profiles=[]
        for i in range(0,len(rows),3):
            station=float(rows[i][0])
            z0=height_at(dmx,station)
            sides=[]
            for r in rows[i+1:i+3]:
                if len(r)!=1+2*int(r[0]):
                    raise ValueError('HDM point count mismatch')
                v=list(map(float,r[1:]))
                x,z=0.,z0
                points=[(x,z)]
                for dx,dz in zip(v[::2],v[1::2]):
                    if not finite((dx,dz)) or dx<0 or (dx==0 and dz!=0):
                        raise ValueError('HDM negative offsets or vertical terrain faces require separate validation')
                    if dx==0:
                        continue
                    x+=dx
                    z+=dz
                    points.append((x,z))
                if len(points)<2:
                    raise ValueError('Empty HDM side')
                sides.append(points)
            self.stations.append(station)
            self.profiles.append(sides)
        increasing(self.stations,'HDM')

    @lru_cache(maxsize=64)
    def ground(self,station,side):
        if not self.stations[0]<=station<=self.stations[-1]:
            raise ValueError('Station outside measured terrain')
        j=bisect.bisect_left(self.stations,station)
        if j<len(self.stations) and self.stations[j]==station:
            return self.profiles[j][0 if side=='LEFT' else 1]
        a=self.profiles[j-1][0 if side=='LEFT' else 1]
        b=self.profiles[j][0 if side=='LEFT' else 1]
        t=(station-self.stations[j-1])/(self.stations[j]-self.stations[j-1])
        limit=min(a[-1][0],b[-1][0])
        xs=sorted({x for p in (a,b) for x,z in p if x<=limit}|{limit})
        return [(x,height_at(a,x)*(1-t)+height_at(b,x)*t) for x in xs]
