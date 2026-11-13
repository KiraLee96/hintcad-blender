"""Portable CLI: preflight, isolated Blender build, persisted-model verification and optional export."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from hintcad import Project


def find_blender(explicit=None):
    if explicit:
        p=Path(explicit).resolve()
        if not p.is_file():
            raise ValueError('Blender executable not found: '+str(p))
        return p
    found=shutil.which('blender') or os.environ.get('BLENDER_EXE')
    if found and Path(found).is_file():
        return Path(found).resolve()
    candidates=[]
    for root in [Path.cwd(),*Path.cwd().parents][:3]:
        candidates.extend(root.glob('tools/blender-*/blender.exe'))
    if os.name=='nt':
        base=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Blender Foundation'
        candidates.extend(base.glob('Blender */blender.exe'))
    if candidates:
        return sorted(candidates)[-1].resolve()
    raise ValueError('Blender not found; provide --blender. The skill does not silently install software')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--project',help='Select a PRJ when the folder contains multiple projects')
    parser.add_argument('--blender')
    parser.add_argument('--stage',choices=['route','pavement','full'],default='full')
    parser.add_argument('--start',type=float)
    parser.add_argument('--end',type=float)
    parser.add_argument('--step',type=float,default=1)
    parser.add_argument('--label-interval',type=int,default=100)
    parser.add_argument('--transition-length',type=float,default=20)
    parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--overwrite',action='store_true')
    parser.add_argument('--export',choices=['supermap'],default=None)
    args=parser.parse_args()
    if args.step<=0 or args.step>20 or args.label_interval<=0 or args.transition_length<0:
        parser.error('Step must be (0,20], label interval positive and transition length nonnegative')
    p=Project(args.input,args.stage,args.project,args.start,args.end)
    out=Path(args.output).resolve()
    if out.is_relative_to(p.folder):
        raise ValueError('Output must be outside the source directory')
    if (out/'model.blend').exists() and not args.overwrite and not args.inspect:
        raise ValueError('Output model already exists; choose a new directory or explicitly use --overwrite')
    out.mkdir(parents=True,exist_ok=True)
    preflight=p.inspect()
    (out/'preflight.json').write_text(json.dumps(preflight,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(preflight,ensure_ascii=False,indent=2),flush=True)
    if args.inspect:
        return
    blender=find_blender(args.blender)
    config=dict(input=str(p.folder),output=str(out),project=str(p.prj) if p.prj else None,
                stage=args.stage,start=args.start,end=args.end,step=args.step,label_interval=args.label_interval,
                transition_length=args.transition_length)
    request=out/'request.json'
    request.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    scripts=Path(__file__).resolve().parent
    env=os.environ.copy()
    env['BLENDER_USER_CONFIG']=str(out/'blender_config')
    env['PYTHONIOENCODING']='utf-8'
    (out/'blender_config').mkdir(exist_ok=True)
    for script,log,model_path in [('blender_build.py','build.log',None),('verify_model.py','verify.log',out/'model.blend')]+(
            [('export_model.py','export.log',out/'model.blend')] if args.export else []):
        command=[str(blender),'--background']
        if model_path:
            command.append(str(model_path))
        command+=['--python-exit-code','1','--python',str(scripts/script),'--',str(request)]
        with (out/log).open('w',encoding='utf-8') as f:
            result=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:
            print((out/log).read_text(encoding='utf-8',errors='replace')[-8000:],file=sys.stderr)
            raise RuntimeError(f'{script} failed: see {out/log}')
        print(script+' OK',flush=True)
    quality=json.loads((out/'quality_report.json').read_text(encoding='utf-8'))
    print(json.dumps(dict(model=str(out/'model.blend'),verification=str(out/'verification.json'),
                          status=quality['status'],warnings=quality['warnings']),ensure_ascii=False,indent=2),flush=True)
    if args.open:
        subprocess.Popen([str(blender),str(out/'model.blend')],env=env)


if __name__=='__main__':
    try:
        main()
    except (ValueError,RuntimeError,OSError) as e:
        print('HINTCAD ERROR: '+str(e),file=sys.stderr)
        sys.exit(1)
