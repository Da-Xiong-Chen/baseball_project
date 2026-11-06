/* Capacity accounting only. No probability or invented inning-to-PA conversion. */
(function(root){
  'use strict';
  function plan(input){
    const integer=(x,label)=>{if(!Number.isSafeInteger(x)||x<0||x>1000)throw Error(label+'須為 0–1000 的整數');return x;};
    const target=integer(input.target,'目標打席數');
    if(!Array.isArray(input.pitchers)||!Array.isArray(input.order))throw Error('請提供投手與接續順序');
    const players=new Map();
    for(const p of input.pitchers){
      if(typeof p.id!=='string'||!p.id.trim()||players.has(p.id))throw Error('投手識別重複或無效');
      if(typeof p.available!=='boolean'||typeof p.retired!=='boolean')throw Error('請確認投手可用與退場狀態');
      const remaining=p.remaining===null?null:integer(p.remaining,'剩餘容量');
      players.set(p.id,{...p,remaining});
    }
    if(new Set(input.order).size!==input.order.length)throw Error('投手不可重複接續');
    let need=target;const allocations=[];
    for(const id of input.order){
      const p=players.get(id);
      if(!p)throw Error('接續投手不在名單內');
      if(p.retired||!p.available)throw Error('已退場或不可用投手不能排入接續');
      if(p.remaining===null)throw Error('請先確認接續投手剩餘容量');
      const assigned=Math.min(need,p.remaining);need-=assigned;
      allocations.push({id,assigned,remaining:p.remaining-assigned,used:assigned>0});
    }
    const used=new Set(allocations.filter(p=>p.used).map(p=>p.id));
    const reserve=[...players.values()].filter(p=>p.available&&!p.retired&&!used.has(p.id)).map(p=>({id:p.id,remaining:p.remaining}));
    return {schema_version:1,unit:'PA',target,covered:target-need,uncovered:need,complete:need===0,allocations,reserve,
      assumption:'容量由使用者確認；僅核算打席容量，不驗證換投義務或推估勝率。'};
  }
  const api={plan};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.BullpenPlan=api;
})(typeof window!=='undefined'?window:globalThis);
