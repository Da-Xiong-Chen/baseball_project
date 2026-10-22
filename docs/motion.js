/* 手機左右滑動手勢：頁面直接切換；短暫操作回饋由 style.css 控制並尊重減少動態效果。 */
(function(root){
  'use strict';
  const doc = root.document;
  const NARROW = '(max-width: 1000px)';
  const SWIPE_MIN = 70, SWIPE_RATIO = 2, SWIPE_MS = 700;
  const matches = q => !!(root.matchMedia && root.matchMedia(q).matches);
  const narrow = () => matches(NARROW);

  /* 手勢：從輸入框、可橫向捲動的表格或標示 data-no-swipe 的區塊開始的滑動不處理，避免誤觸。 */
  function swipeBlocked(target) {
    for (let n = target; n && n !== doc.body && n.nodeType === 1; n = n.parentElement) {
      if (n.matches('input,select,textarea,dialog,[data-no-swipe]')) return true;
      if (n.scrollWidth > n.clientWidth + 2 && /(auto|scroll)/.test(root.getComputedStyle(n).overflowX)) return true;
    }
    return false;
  }
  /* 回傳 'left' / 'right' / null（沒有達到明確的水平滑動） */
  function swipeDirection(dx, dy, ms) {
    if (ms > SWIPE_MS || Math.abs(dx) < SWIPE_MIN || Math.abs(dx) < SWIPE_RATIO * Math.abs(dy)) return null;
    return dx < 0 ? 'left' : 'right';
  }
  function onSwipe(handler) {
    let start = null;
    doc.addEventListener('touchstart', e => {
      start = e.touches.length === 1 && narrow() && !swipeBlocked(e.target)
        ? {x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now(), target: e.target} : null;
    }, {passive: true});
    doc.addEventListener('touchend', e => {
      if (!start) return;
      const t = e.changedTouches[0], s = start;
      start = null;
      const dir = swipeDirection(t.clientX - s.x, t.clientY - s.y, Date.now() - s.t);
      if (dir) handler(dir, s.target);
    }, {passive: true});
    doc.addEventListener('touchcancel', () => { start = null; }, {passive: true});
  }

  const api = {swipeDirection, swipeBlocked, onSwipe, narrow};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Motion = api;
})(typeof window !== 'undefined' ? window : globalThis);
