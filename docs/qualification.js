"use strict";
/* Product eligibility from each player's own records. Priors never count as observations. */
const Qualification = (() => {
  let data;
  const innings = outs => `${Math.floor(outs / 3)}${outs % 3 ? ` 局 ${outs % 3} 出局` : ' 局'}`;
  function configure(value) { data = value; }
  function annotate(result) {
    const profile = data?.cutoffs[result.model_cutoff];
    const policy = data?.policy;
    result.ambiguous_players = profile?.ambiguous || [];
    const annotateRow = (row, pitcher) => {
      const own = profile?.[pitcher ? 'pitchers' : 'hitters']?.[row[pitcher ? '投手' : '球員']];
      const minimum = pitcher ? policy?.min_outs : policy?.min_pa;
      row['個人樣本'] = own?.[0] ?? null;
      row['樣本單位'] = pitcher ? '出局數' : '打席';
      row['樣本門檻'] = minimum ?? null;
      row['最近出賽'] = own?.[1] ?? null;
      row['個人投球數'] = pitcher ? own?.[2] ?? null : null;
      row['推薦已驗證'] = policy?.decision_validated ?? false;
      row['可列入排名'] = !!own && Number.isFinite(minimum) && own[0] >= minimum && (!pitcher || !policy?.min_np || (own[2] ?? -1) >= policy.min_np);
      row['樣本資格說明'] = !own ? '個人紀錄不足，未列入排名' : `${own[0]} ${row['樣本單位']} / 門檻 ${minimum}${pitcher ? `（${innings(minimum)}）` : ''}${row['可列入排名'] ? '' : '；未列入排名'}`;
      if (pitcher && own) row['樣本資格說明'] += `；累計 ${row['個人投球數'] ?? '未知'} 球`;
      if (policy?.mode === 'observed-only' && own) row['樣本資格說明'] = `${pitcher ? `${row['個人投球數'] ?? '未知'} 球、${innings(own[0])}` : `${own[0]} 打席`}；${row['可列入排名'] ? '有個人紀錄，可作估計比較；可靠度未驗證' : '缺乏可用個人紀錄，停止比較'}`;
      if (profile?.ambiguous?.includes(row[pitcher ? '投手' : '球員'])) row['樣本資格說明'] = '同名對應不同球員 ID，無法隔離個人紀錄；未列入排名';
    };
    result.candidates.forEach(x => annotateRow(x, false));
    result.bullpen.rows.forEach(x => annotateRow(x, true));
    const opponent = profile?.pitchers[result.situation?.pitcher];
    result.opponent_sample = opponent?.[0] ?? null;
    if (!opponent || opponent[0] < (policy?.min_outs ?? Infinity) || (policy?.min_np && (opponent[2] ?? -1) < policy.min_np)) result.candidates.forEach(x => {
      x['可列入排名'] = false;
      x['樣本資格說明'] += profile?.ambiguous?.includes(result.situation?.pitcher) ? '；對方投手同名 ID 衝突，停止比較' : '；對方投手個人投球樣本不足';
    });
    const thin = (result.bullpen.next || []).filter(name => (profile?.hitters[name]?.[0] ?? 0) < (policy?.min_pa ?? Infinity));
    if (thin.length) result.bullpen.rows.forEach(x => {
      x['可列入排名'] = false;
      x['樣本資格說明'] += `；後續打者個人樣本不足：${thin.join('、')}`;
    });
    for (const [rows, role] of [[result.candidates, '現任'], [result.bullpen.rows, '場上']]) {
      const current = rows.find(x => x['角色'] === role);
      if (current && !current['可列入排名']) rows.filter(x=>x !== current).forEach(x=>{
        x['可列入排名'] = false;
        x['樣本資格說明'] += '；現任基準個人資料不足，暫不比較';
      });
    }
    result.sample_policy = policy;
    return result;
  }
  return {configure, annotate, innings};
})();
