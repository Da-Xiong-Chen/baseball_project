"""Actual HTTP integration after normal server.py startup. No mocked models."""
import json
import time
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8011').rstrip('/')+'/'
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def request(path,body=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,
                              headers={'Content-Type':'application/json'})
    with OPENER.open(req,timeout=120) as r:return json.load(r)


def main():
    report={'routes':{},'invalid_requests':0,'pitch_change_ms':[]}
    meta=request('api/meta'); assert len(meta['teams'])==6;report['routes']['meta']='pass'
    fixtures=json.loads((ROOT/'tests/fixtures/qa_scenarios.json').read_text(encoding='utf8'))
    for body in fixtures[:3]:
        data=request('api/evaluate',body)
        assert data['situation']['pitcher']==body['pitcher']
        assert len(data['candidates'])==len(body['bench'])+1
        assert len(data['bullpen']['rows'])==len(body['pen'])+1
    report['routes']['evaluate']='pass (3 scenarios)'
    team=meta['teams'][0]
    assert request('api/team?'+urllib.parse.urlencode({'team':team}))['hitters'];report['routes']['team']='pass'
    games=request('api/games?'+urllib.parse.urlencode({'team':team}));report['routes']['games']='pass'
    gid=games[0]['game'];pas=request('api/game?game='+gid);assert pas;report['routes']['game']='pass'
    body=fixtures[0]
    assert request('api/detail?'+urllib.parse.urlencode(dict(batter=body['due'],pitcher=body['pitcher'],date='2026-01-01')))['batter']==body['due']
    report['routes']['detail']='pass'
    for pid in ['2025-340-a000', '2025-340-h018', '2025-341-a026']:
        for decision in ['ph', 'pen']:
            result=request('api/replay?'+urllib.parse.urlencode(dict(pa=pid,decision=decision)))
            assert result['replay_context']['decision']==decision
            context=result['replay_context']
            expected=context['incumbent_pitcher'] if decision=='pen' else context['actual_pitcher']
            assert result['situation']['pitcher']==expected
            assert result['ml_cutoff']<=result['model_cutoff']<='2025-09-20'
    report['routes']['replay']='pass (3 PAs, both decision contexts)'
    try:
        request('api/replay?pa=2025-340-a000&decision=unknown')
        raise AssertionError('unknown replay decision accepted')
    except urllib.error.HTTPError as e:
        assert e.code==400
        report['invalid_requests']+=1
    for payload in [b'{', b'\xff', b'']:
        req=urllib.request.Request(BASE+'api/evaluate',data=payload,headers={'Content-Type':'application/json'})
        try:urllib.request.urlopen(req,timeout=10);raise AssertionError('malformed JSON accepted')
        except urllib.error.HTTPError as e:
            assert e.code==400
            assert 'error' in json.load(e)
            report['invalid_requests']+=1
    for extra in [{'bat_score':-1},{'inning':1.5},{'fld_team':body['bat_team']},{'next_batters':[body['due']]*3}]:
        try:request('api/evaluate',{**body,**extra});raise AssertionError('invalid accepted')
        except urllib.error.HTTPError as e:assert e.code==400;report['invalid_requests']+=1
    for hand in ['ALL','L','R']:
        path='api/pitch-change?'+urllib.parse.urlencode(dict(pitcher='鋼龍',season=2025,cutoff='2025-09-27',hand=hand))
        for _ in range(5):
            start=time.perf_counter();data=request(path);report['pitch_change_ms'].append((time.perf_counter()-start)*1000)
            assert all(g['date']<'2025-09-27' for w in data['windows'].values() for g in w['games'])
    report['routes']['pitch-change']='pass (3 hands, 15 requests)'
    for q in [dict(pitcher='unknown',cutoff='2025-09-27'),dict(pitcher='鋼龍',cutoff='2025-02-30'),dict(pitcher='鋼龍',cutoff='2025-09-27',hand='S')]:
        try:request('api/pitch-change?'+urllib.parse.urlencode(q));raise AssertionError('invalid accepted')
        except urllib.error.HTTPError as e:assert e.code==400;report['invalid_requests']+=1
    (ROOT/'output/closeout/http_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
