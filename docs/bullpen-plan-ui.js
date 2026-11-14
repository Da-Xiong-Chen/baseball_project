(function (root) {
  'use strict';

  function escapeHtml(value) {
    const entities = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
    return String(value).replace(/[&<>"']/g, char => entities[char]);
  }

  function mount({element, snapshot, label}) {
    if (!element) return;
    const q = selector => element.querySelector(selector);
    const orderSelectors = ['[data-order]', '[data-order-b]'];
    let source = null;
    let hasResult = false;

    element.innerHTML = `
      <summary>牛棚接續規劃</summary>
      <div class="capacity-body">
        <p class="mut">依自行確認的打席容量安排接續，檢查是否夠用。</p>
        <button type="button" class="link" data-refresh>帶入已選牛棚</button>
        <label class="f">預計涵蓋打席數
          <input data-target type="number" min="1" max="1000" step="1" inputmode="numeric" placeholder="例如 6">
        </label>
        <label class="capacity-compare"><input type="checkbox" data-compare> 比較方案 B</label>
        <p class="mut" data-compare-hint hidden>兩個方案共用目標、投手狀態和容量，各自設定接續順位。</p>
        <div data-rows class="capacity-rows"></div>
        <button type="button" class="btn-primary" data-calculate>檢查接續</button>
        <div data-output role="status" aria-live="polite" aria-atomic="true"></div>
      </div>`;

    const compare = q('[data-compare]');
    const output = q('[data-output]');
    const calculate = q('[data-calculate]');

    function clear() {
      hasResult = false;
      output.textContent = '';
      element.querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
    }

    function edited(event) {
      event.target?.removeAttribute?.('aria-invalid');
      if (!hasResult) return;
      hasResult = false;
      output.textContent = '設定已變更，請重新檢查接續。';
    }

    function showComparison() {
      q('[data-compare-hint]').hidden = !compare.checked;
      element.querySelectorAll('[data-plan-b]').forEach(field => { field.hidden = !compare.checked; });
      if (!compare.checked) {
        element.querySelectorAll('[data-order-b]').forEach(field => field.removeAttribute('aria-invalid'));
      }
    }

    function refresh() {
      source = snapshot();
      clear();
      calculate.disabled = !source.pitchers.length;
      compare.disabled = calculate.disabled;
      const options = '<option value="">保留</option>' + source.pitchers.map((_, i) =>
        `<option value="${i + 1}">${i + 1}</option>`).join('');
      q('[data-rows]').innerHTML = source.pitchers.map((player, i) => {
        const name = escapeHtml(label(player.id));
        return `<fieldset class="capacity-arm" data-arm="${i}">
          <legend>${name}</legend>
          <label>狀態<select data-status aria-label="${name}狀態"><option value="available">可用</option><option value="unavailable">不使用</option><option value="retired">已退場</option></select></label>
          <label>剩餘打席容量<input data-capacity type="number" min="0" max="1000" step="1" inputmode="numeric" aria-label="${name}剩餘容量" placeholder="請確認"></label>
          <label>方案 A 順位<select data-order aria-label="${name}接續順位（方案 A）">${options}</select></label>
          <label data-plan-b hidden>方案 B 順位<select data-order-b aria-label="${name}接續順位（方案 B）">${options}</select></label>
        </fieldset>`;
      }).join('') || '<p class="mut">請先選取牛棚投手，再帶入。</p>';
      showComparison();
    }

    function fail(message, field) {
      if (field) {
        field.setAttribute('aria-invalid', 'true');
        field.focus();
      }
      throw Error(message);
    }

    function integerField(field, min) {
      const value = Number(field.value);
      return field.checkValidity() && Number.isSafeInteger(value) && value >= min && value <= 1000;
    }

    function readPitchers(rows) {
      return rows.map((row, i) => {
        const {id} = source.pitchers[i];
        const status = row.querySelector('[data-status]').value;
        const capacity = row.querySelector('[data-capacity]');
        if (capacity.value !== '' && !integerField(capacity, 0)) {
          fail(label(id) + '的剩餘容量請填寫 0–1000 的整數。', capacity);
        }
        return {id, available: status === 'available', retired: status === 'retired',
          remaining: capacity.value === '' ? null : Number(capacity.value)};
      });
    }

    function readOrder(rows, pitchers, selector, planName) {
      const ordered = new Map();
      rows.forEach((row, i) => {
        const order = row.querySelector(selector);
        if (!order.value) return;
        const player = pitchers[i];
        const name = label(player.id);
        if (!player.available) fail(name + '目前不可接續；請改為可用或將順位設為保留。', row.querySelector('[data-status]'));
        if (player.remaining === null) fail('請填寫' + name + '的剩餘打席容量。', row.querySelector('[data-capacity]'));
        const rank = Number(order.value);
        if (ordered.has(rank)) fail(planName + '的接續順位不可重複，請調整' + name + '的順位。', order);
        ordered.set(rank, player.id);
      });
      if (!ordered.size) fail(planName + '請至少安排一位接續投手的順位。', rows[0]?.querySelector(selector));
      return [...ordered].sort(([left], [right]) => left - right).map(([, id]) => id);
    }

    function renderPlan(result, title) {
      const status = result.complete ? '容量足夠' : `尚缺 ${result.uncovered} 打席容量`;
      const used = result.allocations.filter(player => player.used);
      const allocation = used.length ? `<ol>${used.map(player =>
        `<li>${escapeHtml(label(player.id))}：安排 ${player.assigned} 打席，剩餘 ${player.remaining}</li>`).join('')}</ol>` : '';
      // 有填容量的保留投手逐一列出；尚未確認容量的合併成一句，避免整串「容量待確認」
      const known = result.reserve.filter(player => player.remaining !== null);
      const pending = result.reserve.length - known.length;
      const reserve = [...known.map(player => `${escapeHtml(label(player.id))}（${player.remaining} 打席）`),
        ...(pending ? [`另 ${pending} 人容量待確認`] : [])].join('、') || '無';
      return `<section class="capacity-result"><h4>${title}</h4><p><strong>${status}</strong> · 已涵蓋 ${result.covered}／${result.target} 打席</p>${allocation}<p>保留：${reserve}</p></section>`;
    }

    q('[data-refresh]').onclick = refresh;
    compare.onchange = showComparison;
    element.addEventListener('toggle', () => {
      if (element.open && (!source || source.key !== snapshot().key)) refresh();
    });
    element.addEventListener('input', edited);
    element.addEventListener('change', edited);
    calculate.onclick = () => {
      try {
        clear();
        if (!source || source.key !== snapshot().key) {
          throw Error('牛棚或場上設定已變更，請重新帶入已選牛棚。');
        }
        const target = q('[data-target]');
        if (!integerField(target, 1)) fail('預計涵蓋打席數請填寫 1–1000 的整數。', target);
        const rows = [...element.querySelectorAll('[data-arm]')];
        const pitchers = readPitchers(rows);
        const selectors = compare.checked ? orderSelectors : orderSelectors.slice(0, 1);
        const plans = selectors.map((selector, i) => {
          const title = i ? '方案 B' : '方案 A';
          const order = readOrder(rows, pitchers, selector, title);
          return {title, result: root.BullpenPlan.plan({target: Number(target.value), pitchers, order})};
        });
        output.innerHTML = `<div class="capacity-results">${plans.map(({title, result}) =>
          renderPlan(result, title)).join('')}</div><small class="mut">${escapeHtml(plans[0].result.assumption)}</small>`;
        hasResult = true;
      } catch (error) {
        output.textContent = error.message;
      }
    };

    return {
      contextChanged() {
        if (!source || source.key === snapshot().key) return;
        clear();
        output.textContent = '牛棚名單已變更，請重新帶入已選牛棚。';
        calculate.disabled = true;
        compare.disabled = true;
      },
    };
  }
  root.BullpenPlanUI = {mount};
})(typeof window !== 'undefined' ? window : globalThis);
