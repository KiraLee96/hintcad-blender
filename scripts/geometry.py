"""Validated HintCAD geometry primitives, independent of project names and Blender."""
import math
import bisect


def horizontal(seg, station):
    length = seg['end']-seg['start']
    distance = station-seg['start']
    if not -1e-6 <= distance <= length+1e-6:
        raise ValueError('Station outside PM segment')
    rate = (seg['k1']-seg['k0'])/length
    if abs(rate)<1e-15:
        k=seg['k0']
        angle=seg['theta']
        if abs(k)<1e-15:
            return seg['xy'][0]+distance*math.cos(angle),seg['xy'][1]+distance*math.sin(angle)
        return (seg['xy'][0]+(math.sin(angle+k*distance)-math.sin(angle))/k,
                seg['xy'][1]+(math.cos(angle)-math.cos(angle+k*distance))/k)
    # Composite Simpson integration with intervals <= 1 m, including clothoids.
    n = max(2, math.ceil(distance/2)*2)
    h = distance/n
    dx = dy = 0.0
    for i in range(n+1):
        s = i*h
        theta = seg['theta']+seg['k0']*s+rate*s*s/2
        w = 1 if i in (0,n) else (4 if i%2 else 2)
        dx += w*math.cos(theta)
        dy += w*math.sin(theta)
    return seg['xy'][0]+dx*h/3, seg['xy'][1]+dy*h/3

def elevation(vpis, station):
    if not vpis[0][0] <= station <= vpis[-1][0]:
        raise ValueError('Station outside ZDM')
    grades = [(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(vpis,vpis[1:])]
    previous_end = vpis[0][0]
    for i in range(1,len(vpis)-1):
        s,z,r,_,_ = vpis[i]
        change = grades[i]-grades[i-1]
        if r <= 0 or change == 0:
            raise ValueError('Invalid interior vertical curve')
        length = r*abs(change)
        start, end = s-length/2, s+length/2
        if start < previous_end or end > vpis[-1][0]:
            raise ValueError('Overlapping/out-of-range vertical curves')
        previous_end = end
        if start <= station <= end:
            x = station-start
            return z-grades[i-1]*length/2+grades[i-1]*x+change*x*x/(2*length)
    i = next((i for i in range(len(grades)) if station <= vpis[i+1][0]),len(grades)-1)
    return vpis[i][1]+grades[i]*(station-vpis[i][0])

def height_at(ground, x):
    if x < ground[0][0]-1e-7 or x > ground[-1][0]+1e-7:
        raise ValueError(f'Terrain does not cover offset {x}: {ground[0][0]}..{ground[-1][0]}')
    i = min(max(1, bisect.bisect_left(ground, x, key=lambda p:p[0])), len(ground)-1)
    a,b = ground[i-1:i+1]
    return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])

def slope_rule(row):
    n = int(row[1])
    data = list(map(float,row[2:]))
    if len(data) not in (4*n,8*n) or not all(math.isfinite(x) for x in data):
        raise ValueError('Unrecognized CTR slope record')
    expanded = len(data)==8*n
    groups = [data[i:i+4] for i in range(0,len(data),4)]
    if any(g[1]!=0 for g in groups):
        raise ValueError('Nonzero control-height extension is not present in this dataset and needs separate validation')
    if expanded and any(groups[i][0]!=0 for i in range(1,len(groups),2)):
        raise ValueError('Extended CTR record must contain slope/bench pairs')
    last_slope = max(i for i,g in enumerate(groups) if g[0]!=0)
    result=[]
    stage=0
    for i,(ratio,control,maximum,lining) in enumerate(groups[:last_slope+1]):
        if maximum<=0 or lining not in (0,1):
            raise ValueError('Invalid CTR height/width or lining flag')
        if ratio:
            stage+=1
        result.append(dict(key=f'{"SLOPE" if ratio else "BENCH"}_{stage}',ratio=ratio,
                           maximum=maximum,lining=int(lining),last=i==last_slope))
    return result

def excluded_ranges(controls, side):
    result=[]
    for r in controls.get('QHSJ.DAT',[]):
        if len(r)!=11:
            raise ValueError('Unexpected bridge CTR format')
        a,b=float(r[0]),float(r[1])
        half=int(r[10])
        if half not in (-1,0,1) or a>=b:
            raise ValueError('Invalid bridge interval/side')
        if half==0 or half==(-1 if side==0 else 1):
            result.append(dict(start=a,end=b,kind='BRIDGE',name=r[3]))
    for r in controls.get('SUIDAO.DAT',[]):
        if len(r)!=3 or float(r[0])>=float(r[1]):
            raise ValueError('Unexpected tunnel CTR format')
        result.append(dict(start=float(r[0]),end=float(r[1]),kind='TUNNEL',name=r[2]))
    return sorted(result,key=lambda r:r['start'])

def active_ranges(start, end, excluded):
    cursor=start
    result=[]
    for r in sorted(excluded,key=lambda r:r['start']):
        a,b=max(start,r['start']),min(end,r['end'])
        if b<=a:
            continue
        if a>cursor:
            result.append((cursor,a))
        cursor=max(cursor,b)
    if cursor<end:
        result.append((cursor,end))
    return result

def first_contact(a,b,ground):
    """Exact intersection with a piecewise-linear measured/interpolated ground line."""
    if a[0]>ground[-1][0]+1e-7:
        raise ValueError('Profile starts outside surveyed terrain')
    dx,dz=b[0]-a[0],b[1]-a[1]
    if abs(dx)<1e-12:
        z=height_at(ground,a[0])
        if min(a[1],b[1])-1e-9<=z<=max(a[1],b[1])+1e-9:
            return (a[0],z)
        return None
    limit=min(b[0],ground[-1][0])
    knots=[a[0]]+[x for x,_ in ground if a[0]<x<limit]+[limit]
    for x0,x1 in zip(knots,knots[1:]):
        h0=a[1]+dz*(x0-a[0])/dx-height_at(ground,x0)
        h1=a[1]+dz*(x1-a[0])/dx-height_at(ground,x1)
        if abs(h0)<1e-9:
            return (x0,height_at(ground,x0))
        if h0*h1<=0 or abs(h1)<1e-9:
            x=x0+(x1-x0)*h0/(h0-h1) if h0!=h1 else x0
            return (x,height_at(ground,x))
    return None

def advance(point, ratio, height):
    if ratio==0:
        return (point[0]+height,point[1])
    return (point[0]+(0 if abs(ratio)==9999 else abs(ratio)*height),
            point[1]+math.copysign(height,ratio))

def solve_profile(edge, ground, rule, ditch=None):
    features=[]
    p=edge
    for i,g in enumerate(ditch or []):
        q=advance(p,g['ratio'],g['height'])
        contact=first_contact(p,q,ground)
        if contact is not None:
            q=contact
        features.append(dict(key=f'DITCH_{i+1}',a=p,b=q,ratio=g['ratio'],lining=g['lining']))
        p=q
        if contact is not None:
            return dict(edge=edge,features=features,contact=p,terminal=p,contact_role='DITCH_DAYLIGHT')
    for g in rule:
        height=g['maximum']
        if g['last']:
            if abs(g['ratio'])==9999:
                height=abs(height_at(ground,p[0])-p[1])+1
            else:
                height=(ground[-1][0]-p[0])/abs(g['ratio'])
        q=advance(p,g['ratio'],height)
        contact=first_contact(p,q,ground)
        if contact is not None:
            q=contact
        if q[0]>ground[-1][0]+1e-7:
            raise ValueError('Terrain coverage exhausted before slope daylight')
        features.append(dict(key=g['key'],a=p,b=q,ratio=g['ratio'],lining=g['lining']))
        p=q
        if contact is not None:
            return dict(edge=edge,features=features,contact=p,terminal=p,contact_role='SLOPE_DAYLIGHT')
    return dict(edge=edge,features=features,contact=None,terminal=p,contact_role='SURVEY_LIMIT_NOT_DAYLIGHT')

def ditch_rule(row):
    data=list(map(float,row[2:]))
    if len(data)!=3*int(row[1]) or not all(math.isfinite(v) for v in data):
        raise ValueError('Unexpected CTR cut-ditch shape')
    if any(data[i+2] not in (0,1) for i in range(0,len(data),3)):
        raise ValueError('Ditch lining flags must be exactly 0 or 1')
    return [dict(ratio=data[i],height=data[i+1],lining=int(data[i+2])) for i in range(0,len(data),3)]

def station_label(station):
    km, remainder = divmod(round(station*1000), 1000000)
    meters, millimeters = divmod(remainder, 1000)
    return f'K{km}+{meters:03d}' + (f'.{millimeters:03d}' if millimeters else '')

def cubic_profile(a,b,da,db,t,length):
    """Ordered Bezier controls avoid overshoot and lateral cross-section inversion."""
    if t==0:
        return list(a)
    if t==1:
        return list(b)
    controls=[]
    for endpoint,tangent,sign in ((a,da,1),(b,db,-1)):
        control=[]
        for p,q,v,d in zip(a,b,endpoint,tangent):
            control.append([max(min(p[k],q[k]),min(max(p[k],q[k]),v[k]+sign*d[k]*length/3)) for k in (0,1)])
        for i in range(1,len(control)):
            control[i][0]=max(control[i][0],control[i-1][0])
        controls.append(control)
    return [tuple((1-t)**3*p[k]+3*(1-t)**2*t*controls[0][i][k]+3*(1-t)*t*t*controls[1][i][k]+t**3*q[k] for k in (0,1))
            for i,(p,q) in enumerate(zip(a,b))]
