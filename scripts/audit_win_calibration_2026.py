"""Rolling 2026 diagnostics for observable win states and the site's RE24 → WPA map."""
import argparse
import json
from pathlib import Path

from evaluate_pa_outcomes_2026 import dataset, load, np, pd, win_tables
from evaluate_half_inning_2026 import paired_interval

from runtime_config import settings
from model import fit


def calibrate(frame):
    samples=[]
    keys=['inning_group','half','home_margin','outs','bases']
    for cutoff in settings().replay_cutoffs:
        after=pd.Timestamp(cutoff)+pd.offsets.MonthBegin()
        earlier=frame[frame.date<cutoff]
        sample=frame[(frame.date>=cutoff)&(frame.date<after)].copy()
        fine,coarse,average=win_tables(earlier)
        state=sample[keys].copy()
        state['home_margin']=state.home_margin.clip(-6,6)
        rows=list(state.itertuples(index=False,name=None))
        sample['prior']=average
        sample['coarse']=[coarse.get(key[:3],average) for key in rows]
        sample['fine']=[fine.get(key,parent) for key,parent in zip(rows,sample.coarse)]
        hierarchy=fit(cutoff)
        sample['slope_wpa']=sample.RE24*np.array([hierarchy.run_to_win(*row) for row in sample[
            ['inning','half','bat_score','fld_score','bases','outs']].itertuples(index=False,name=None)])
        sample['league_wpa']=sample.RE24*hierarchy.slope_all
        samples.append(sample)
    return pd.concat(samples)


def describe(frame):
    methods=('prior','coarse','fine')
    data={k:{'mean':float(frame[k].mean()),'mse':float((frame[k]-frame.home_result).pow(2).mean())}
          for k in methods}
    data['actual_home_win_equivalent']=float(frame.home_result.mean())
    data['games']=int(frame.game.nunique())
    data['pa']=len(frame)
    scored=frame.dropna(subset=['WPA','slope_wpa','league_wpa'])
    e=(scored.slope_wpa-scored.WPA).pow(2)
    baseline=(scored.league_wpa-scored.WPA).pow(2)
    data['wpa_mapping']={'pa':len(scored),'slope_mse':float(e.mean()),'league_mse':float(baseline.mean()),
                         'delta_ci':paired_interval(scored,e-baseline)}
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if settings().season!=2026 or args.out.exists():
        parser.error('Provide the 2026 runtime and an unused output file')
    frame,_=dataset(load()[0])
    frame=calibrate(frame)
    subsets={'overall':frame,'late_close':frame[frame.inning.ge(8)&frame.home_margin.abs().le(1)],
             'extra_innings':frame[frame.inning.gt(9)],
             'walkoff_possible':frame[frame.inning.ge(9)&frame.half.eq('home')&frame.home_margin.eq(0)],
             'rare_bases_two_outs':frame[frame.outs.eq(2)&frame.bases.eq(7)]}
    buckets=pd.cut(frame.fine,np.arange(11)/10,include_lowest=True)
    output={'season':2026,'groups':{k:describe(v) for k,v in subsets.items()},
            'fine_reliability':[{'band':str(band),'pa':len(group),'average':float(group.fine.mean()),
                                 'actual':float(group.home_result.mean())}
                                for band,group in frame.groupby(buckets,observed=True)],
            'scope':'Full prior-month game cutoff. Draw coded as half win. Reads official end scores as labels only. Site slope approximation is diagnosed on observed PA, not a candidate change counterfactual.'}
    args.out.write_text(json.dumps(output,allow_nan=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(output['groups']['overall'],indent=2))

if __name__=='__main__':
    main()
