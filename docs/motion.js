/* 低調的滑動效果：頁面左右滑入、手機左右滑動手勢、窄螢幕結果抽屜。
   開啟「減少動態效果」時不播放動畫（與 style.css 的規則一致），手勢與抽屜仍可使用。 */
(function(root){
  'use strict';
  const doc = root.document;
  const NARROW = '(max-width: 1000px)';
  const SWIPE_MIN = 70, SWIPE_RATIO = 2, SWIPE_MS = 700;
  const matches = q => !!(root.matchMedia && root.matchMedia(q).matches);
  const reduced = () => matches('(prefers-reduced-motion: reduce)') && doc.documentElement.dataset.motion !== 'on';
  const narrow = () => matches(NARROW);

  /* dir > 0：新內容從右邊滑入（往後一頁）；dir < 0：從左邊滑入（回上一頁） */
  function slideIn(el, dir) {
    if (!el || !dir || reduced()) return;
    el.classList.remove('slide-from-right', 'slide-from-left');
    void el.offsetWidth;  // 重新觸發動畫
    const cls = dir > 0 ? 'slide-from-right' : 'slide-from-left';
    el.classList.add(cls);
    const done = () => el.classList.remove(cls);
    el.addEventListener('animationend', done, {once: true});
    setTimeout(done, 400);  // 分頁在背景時 animationend 可能不會觸發
  }

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

  /* 窄螢幕結果抽屜：從右側滑出蓋住畫面，返回鍵、Esc、向右滑或「返回」都會關閉。 */
  let drawer = null;
  const BACKGROUND = 'header, .feature-nav, .matchday-intro, .mobile-jump, #workspace';
  function setupDrawer(o) {
    drawer = {el: o.element, onClose: o.onClose, open: false};
    root.addEventListener('popstate', () => { if (drawer.open) closeNow(); });
    doc.addEventListener('keydown', e => { if (e.key === 'Escape' && drawer.open) closeDrawer(); });
    root.matchMedia && root.matchMedia(NARROW).addEventListener?.('change', e => { if (!e.matches && drawer.open) closeNow(); });
  }
  function openDrawer() {
    if (!drawer || !narrow()) return false;
    if (!drawer.open) {
      drawer.open = true;
      drawer.el.scrollTop = 0;
      doc.body.classList.add('result-drawer');
      doc.querySelectorAll(BACKGROUND).forEach(n => { n.inert = true; });
      if (!(root.history.state && root.history.state.resultDrawer)) root.history.pushState({resultDrawer: true}, '');
    }
    drawer.el.focus({preventScroll: true});
    return true;
  }
  function closeNow() {
    if (!drawer || !drawer.open) return;
    drawer.open = false;
    const finish = () => {
      drawer.el.classList.remove('drawer-closing');
      doc.body.classList.remove('result-drawer');
      doc.querySelectorAll(BACKGROUND).forEach(n => { n.inert = false; });
      drawer.onClose && drawer.onClose();
    };
    if (reduced()) { finish(); return; }
    drawer.el.classList.add('drawer-closing');
    let done = false;
    const once = () => { if (!done) { done = true; finish(); } };
    drawer.el.addEventListener('animationend', once, {once: true});
    setTimeout(once, 400);  // 動畫事件沒觸發時的保險
  }
  function closeDrawer() {
    if (!drawer || !drawer.open) return;
    if (root.history.state && root.history.state.resultDrawer) root.history.back();  // 由 popstate 收起
    else closeNow();
  }
  const drawerOpen = () => !!(drawer && drawer.open);

  const api = {slideIn, swipeDirection, swipeBlocked, onSwipe, setupDrawer, openDrawer, closeDrawer, drawerOpen, narrow};
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Motion = api;
})(typeof window !== 'undefined' ? window : globalThis);
