"""Project-independent road sampling, slope daylighting, ditches and local transitions."""
import math
from geometry import elevation, height_at, active_ranges, excluded_ranges, slope_rule, solve_profile, advance, cubic_profile


def grid(a,b,step):
    return {a,b}|{round(i*step,9) for i in range(math.ceil(a/step),math.floor(b/step)+1)}


def breakpoints(project,a,b,step):
    ss=grid(a,b,step)
    ss.update(s[k] for s in project.segments for k in ('start','end') if a<s[k]<b)
    ss.update(v[0] for v in project.vpis if a<v[0]<b)
    if project.stage!='route':
        ss.update(s for sides in project.slopes.values() for channel in sides for s,_ in channel if a<s<b)
        ss.update(row[0] for pairs in project.widths.values() for pair in pairs for row in pair if a<row[0]<b)
    if project.stage=='full':
        ss.update(s for s in project.terrain.stations if a<s<b)
        ss.update(float(row[0]) for key,records in project.controls.items() if key.endswith(('FBP.DAT','GXS.DAT'))
                  for row in records if a<float(row[0])<b)
    return ss


def record(project,station,side,run):
    ground=project.terrain.ground(station,side)
    edge=project.edge(station,side)
    raw=solve_profile(edge,ground,run['rule'],run['cut_shape'])
    raw['station']=station
    raw['bands']={f['key']:dict(f,role='WATER' if f['key'].startswith('DITCH') else 'BENCH' if f['key'].startswith('BENCH') else run['mode']) for f in raw['features']}
    channel=None
    if run['mode']=='FILL' and raw['contact'] is not None:
        p=raw['contact']
        water=[p]
        for i,g in enumerate(run['fill_shape']):
            q=advance(p,g['ratio'],g['height'])
            raw['bands'][f'DRAIN_{i}']=dict(a=p,b=q,ratio=g['ratio'],lining=g['lining'],role='BERM' if i==0 and g['ratio']==0 else 'WATER')
            p=q
            water.append(p)
        shape=run['fill_shape']
    elif run['mode']=='CUT':
        water=[edge]
        for i,g in enumerate(run['cut_shape']):
            feature=raw['bands'].get(f'DITCH_{i+1}')
            water.append(feature['b'] if feature else raw['terminal'])
        shape=run['cut_shape']
    else:
        water=[]
        shape=[]
    j=0
    while j<len(shape) and shape[j]['ratio']==0:
        j+=1
    if len(shape)-j==3 and shape[j]['ratio']<0 and shape[j+1]['ratio']==0 and shape[j+2]['ratio']>0:
        channel=water[j:j+4]
    raw['channel']=channel
    return raw


def calculate(project,step=1,transition_length=20):
    road=sorted(breakpoints(project,project.start,project.end,step))
    result=dict(road_stations=road,runs=[],transitions=[],windows=[],warnings=[],unresolved=[],skipped_transitions=[])
    if project.stage!='full':
        return result
    for i,side in enumerate(('LEFT','RIGHT')):
        prefix='Z' if side=='LEFT' else 'Y'
        excluded=excluded_ranges(project.controls,i)

        def difference(s):
            x,z=project.edge(s,side)
            return z-height_at(project.terrain.ground(s,side),x)

        for lo,hi in active_ranges(project.start,project.end,excluded):
            ss=breakpoints(project,lo,hi,step)
            original=sorted(ss)
            for a,b in zip(original,original[1:]):
                da,db=difference(a),difference(b)
                if da*db<0:
                    left,right=a,b
                    for _ in range(32):
                        mid=(left+right)/2
                        if difference(mid)*da>0:
                            left=mid
                        else:
                            right=mid
                    ss.add((left+right)/2)
            runs=[]
            ordered=sorted(ss)
            for a,b in zip(ordered,ordered[1:]):
                s=(a+b)/2
                mode='FILL' if difference(s)>=0 else 'CUT'
                slope=project.control(prefix+('TFBP.DAT' if mode=='FILL' else 'WFBP.DAT'),s)
                ditch=project.control(prefix+('PSGXS.DAT' if mode=='FILL' else 'BGXS.DAT'),s)
                signature=(mode,tuple(slope),tuple(ditch))
                if runs and runs[-1]['signature']==signature:
                    runs[-1]['stations'].append(b)
                else:
                    runs.append(dict(signature=signature,mode=mode,side=side,stations=[a,b],slope_row=slope,ditch_row=ditch,
                                     rule=slope_rule(slope),cut_shape=project.validate_ditch(ditch) if mode=='CUT' else [],
                                     fill_shape=project.validate_ditch(ditch) if mode=='FILL' else [],excluded=excluded))
            for run in runs:
                sign=-1 if run['mode']=='FILL' else 1
                if any(g['ratio']*sign<0 for g in run['rule']):
                    raise ValueError('CTR slope direction contradicts cut/fill classification')
                run['start'],run['end']=run['stations'][0],run['stations'][-1]
                run['profiles']=[record(project,s,side,run) for s in run['stations']]
                for p in run['profiles']:
                    if p['contact'] is None:
                        result['unresolved'].append(dict(side=side,station=p['station'],mode=run['mode'],terminal=p['terminal']))
                    elif abs(p['contact'][1]-height_at(project.terrain.ground(p['station'],side),p['contact'][0]))>1e-6:
                        raise ValueError('Slope daylight residual exceeds tolerance')
                result['runs'].append(run)
    if transition_length<=0:
        return result
    runs=result['runs']
    for i,(a,b) in enumerate(zip(runs,runs[1:])):
        if a['side']!=b['side'] or a['mode']==b['mode'] or abs(a['end']-b['start'])>1e-6:
            continue
        root=a['end']
        half=min(transition_length/2,.4*(a['end']-a['start']),.4*(b['end']-b['start']))
        lo=math.ceil((root-half)/step)*step
        hi=math.floor((root+half)/step)*step
        if not lo<root<hi:
            result['skipped_transitions'].append(dict(side=a['side'],station=root,reason='Adjacent run too short'))
            continue
        if any(lo<e['end'] and hi>e['start'] for e in a['excluded']):
            continue
        fill_run=a if a['mode']=='FILL' else b
        cut_run=a if a['mode']=='CUT' else b
        pre_keys=[g['key'] for g in fill_run['rule']]
        post_keys=[g['key'] for g in cut_run['rule']]

        def common(s,run):
            p=record(project,s,run['side'],run)
            if p['contact'] is None or p['channel'] is None:
                raise ValueError('Endpoint lacks daylight or a three-part channel')
            edge=p['edge']
            if run['mode']=='FILL':
                before=[p['bands'].get(k,dict(b=p['terminal']))['b'] for k in pre_keys]
                after=[p['channel'][-1]]*len(post_keys)
            else:
                before=[edge]*len(pre_keys)
                after=[p['bands'].get(k,dict(b=p['terminal']))['b'] for k in post_keys]
            points=[edge]+before+p['channel']+after
            return [(x-edge[0],z-edge[1]) for x,z in points],points
        try:
            ra,pa=common(lo,a)
            rb,pb=common(hi,b)
            oa,_=common(lo-min(.25,step/4),a)
            ob,_=common(hi+min(.25,step/4),b)
            epsilon=min(.25,step/4)
            da=[tuple((x-y)/epsilon for x,y in zip(p,q)) for p,q in zip(ra,oa)]
            db=[tuple((x-y)/epsilon for x,y in zip(p,q)) for p,q in zip(ob,rb)]
        except ValueError as e:
            result['skipped_transitions'].append(dict(side=a['side'],station=root,reason=str(e)))
            continue
        n=len(pre_keys)
        roles=[('BENCH' if k.startswith('BENCH') else 'FILL') for k in pre_keys]+['BERM']+['WATER']*3+[
            'BENCH' if k.startswith('BENCH') else 'CUT' for k in post_keys]
        samples=[]
        count=max(4,math.ceil((hi-lo)/min(.25,step)))
        for j in range(count+1):
            s=lo+(hi-lo)*j/count
            rel=cubic_profile(ra,rb,da,db,j/count,hi-lo)
            if any(q[0]<p[0]-1e-7 for p,q in zip(rel,rel[1:])):
                raise ValueError('Transition cross-section folds laterally')
            edge=project.edge(s,a['side'])
            points=[(edge[0]+x,edge[1]+z) for x,z in rel]
            if j==0:
                points=pa
            elif j==count:
                points=pb
            samples.append(dict(station=s,points=points))
        window=dict(side=a['side'],root=root,start=lo,end=hi)
        result['windows'].append(window)
        result['transitions'].append(dict(**window,roles=roles,samples=samples,channel_index=n+1))
    if result['skipped_transitions']:
        result['warnings'].append('Some transitions were not applied; see skipped_transitions for exact reasons')
    return result


def outside_window(a,b,side,windows):
    return not any(w['side']==side and a>=w['start']-1e-7 and b<=w['end']+1e-7 for w in windows)
