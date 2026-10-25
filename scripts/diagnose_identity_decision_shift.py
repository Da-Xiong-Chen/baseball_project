"""Read-only component readback from a specified code/model snapshot."""
import argparse,hashlib,json,os,sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--code-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    code=args.code_root.resolve();sys.path[:0]=[str(code),str(code/'src')]
    import server,engine,mlmodel,timing_backtest as timing
    from batch_contract import metadata
    points=timing.decision_points().set_index('pa_id');results=[]
    for pid in ['2025-339-h024','2025-127-h029','2025-064-h028','2025-068-h036']:
        r=points.loc[pid];day=str(r.date.date());sit=engine.situation(pid);m=server.model_for(day);ml=mlmodel.for_date(day)
        ps=timing.incumbent_situation(sit,r);pen,_=engine.evaluate_bullpen(ps,model=m,ml=ml,scores=False)
        ph,_,_=engine.evaluate_pinch_hit(sit,model=m,ml=ml,scores=False)
        slope=m.run_to_win(sit['row']['inning'],sit['row']['half'],sit['row']['bat_score'],sit['row']['fld_score'],sit['row']['bases'],sit['row']['outs'])
        results.append(server.clean(dict(pa_id=pid,slope=slope,opening_pitcher=sit['row']['pitcher'],due=sit['due'],
            incumbent=ps['row']['pitcher'],inc_hand=ps['row']['phand'],pitch_count=ps['pitch_count'],
            bullpen=pen,candidates=ph)))
        server._models.pop(day,None);print('Diagnosed '+pid,flush=True)
    report=dict(results=results,**metadata(),source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (code/'src').glob('*.py')})
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
