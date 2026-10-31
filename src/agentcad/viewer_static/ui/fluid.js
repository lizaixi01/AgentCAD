// AgentCAD UI kit behaviours, ported from Fluid Functionalism (MIT, (c) 2026 Micka Touillaud): spring curves, the
// gliding hover highlight, the gliding segmented indicator, tooltips, popovers, dialogs and toasts. No framework.
(function (global) {
  "use strict";

  // ---- springs ---------------------------------------------------------------------------------------------------
  // A spring sampled into CSS linear(): critically damped for bounce 0, a little overshoot otherwise. The tiers are
  // the original's (fast 0.08 s, moderate 0.16 s, slow 0.24 s with bounce 0.12); a sampled curve is what lets CSS
  // transitions feel like springs without a JS animation loop.
  function springCurve(duration, bounce) {
    const zeta = 1 - bounce, w = 6.6 / (duration * (zeta < 1 ? 1.15 : 1)); // settles within ~1% by `duration`
    const pts = [], n = 24;
    for (let i = 0; i <= n; i++) {
      const t = (i / n) * duration;
      let x;
      if (zeta >= 1) x = 1 - (1 + w * t) * Math.exp(-w * t);
      else {
        const wd = w * Math.sqrt(1 - zeta * zeta);
        x = 1 - Math.exp(-zeta * w * t) * (Math.cos(wd * t) + (zeta * w / wd) * Math.sin(wd * t));
      }
      pts.push(i === n ? 1 : Math.round(x * 10000) / 10000);
    }
    return `${Math.round(duration * 1000)}ms linear(${pts.join(", ")})`;
  }
  const SPRINGS = { fast: [0.08, 0], moderate: [0.16, 0], slow: [0.24, 0.12] };
  try {
    if (CSS.supports("transition-timing-function", "linear(0, 1)")) {
      const root = document.documentElement.style;
      for (const [k, [d, b]] of Object.entries(SPRINGS)) root.setProperty(`--spring-${k}`, springCurve(d, b));
    }
  } catch (e) { /* older browser: the CSS fallbacks stay */ }

  // ---- fluid hover: one highlight glides to the item under (or nearest) the pointer --------------------------------
  // fluidHover(list, {item: ".ff-item", nearest: false}). The highlight fades in where the pointer enters, glides
  // between items while it stays, fades out when it leaves. With nearest, the gap between items lights the closest.
  function fluidHover(list, opts = {}) {
    const sel = opts.item || ".ff-item";
    let hl = list.querySelector(":scope > .ff-hl");
    if (!hl) { hl = document.createElement("div"); hl.className = "ff-hl"; list.prepend(hl); }
    let current = null, entering = true;
    const place = (el) => {
      if (current) current.classList.remove("lit");
      current = el;
      if (!el) { hl.classList.remove("on"); return; }
      el.classList.add("lit");
      const box = list.getBoundingClientRect(), r = el.getBoundingClientRect();
      const x = r.left - box.left + list.scrollLeft, y = r.top - box.top + list.scrollTop;
      if (entering) { hl.classList.add("jump"); }  // appear in place, do not slide in from the last spot
      hl.style.transform = `translate(${x}px, ${y}px)`;
      hl.style.width = r.width + "px"; hl.style.height = r.height + "px";
      hl.style.borderRadius = getComputedStyle(el).borderRadius;
      if (entering) { void hl.offsetWidth; hl.classList.remove("jump"); entering = false; }
      hl.classList.add("on");
    };
    const items = () => [...list.querySelectorAll(sel)].filter((el) => !el.hidden && !el.disabled);
    list.addEventListener("pointermove", (e) => {
      if (e.pointerType === "touch") return;
      let el = e.target.closest(sel);
      if (el && !list.contains(el)) el = null;
      if (!el && opts.nearest) {
        let best = null, bd = Infinity;
        for (const it of items()) {
          const r = it.getBoundingClientRect(), d = Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2));
          if (d < bd) { bd = d; best = it; }
        }
        el = best;
      }
      if (el !== current) place(el);
    });
    list.addEventListener("pointerleave", () => { place(null); entering = true; });
    list.addEventListener("focusin", (e) => { const el = e.target.closest(sel); if (el && e.target.matches(":focus-visible")) place(el); });
    list.addEventListener("focusout", () => { if (!list.matches(":hover")) { place(null); entering = true; } });
    return { refresh: () => current && place(current) };
  }

  // ---- segmented control: the indicator glides to the pressed option -------------------------------------------
  function segmented(group, onChange) {
    let ind = group.querySelector(":scope > .ff-seg-ind");
    if (!ind) { ind = document.createElement("span"); ind.className = "ff-seg-ind"; group.prepend(ind); }
    const buttons = () => [...group.querySelectorAll(":scope > button")];
    const move = (instant) => {
      const on = buttons().find((b) => b.getAttribute("aria-pressed") === "true");
      if (!on) { ind.style.opacity = "0"; return; }
      if (instant) ind.style.transition = "none";
      ind.style.opacity = "1";
      ind.style.width = on.offsetWidth + "px";
      ind.style.transform = `translateX(${on.offsetLeft}px)`;
      if (instant) { void ind.offsetWidth; ind.style.transition = ""; }
    };
    group.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || !group.contains(b)) return;
      buttons().forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      move(false);
      if (onChange) onChange(b.value || b.dataset.value, b);
    });
    new ResizeObserver(() => move(true)).observe(group);
    move(true);
    return { set(value) { buttons().forEach((x) => x.setAttribute("aria-pressed", String((x.value || x.dataset.value) === value))); move(false); } };
  }

  // ---- tooltip: [data-tip] shows after a short dwell, leaves at once --------------------------------------------
  let tip = null, tipTimer = 0;
  function tooltips(root = document) {
    if (!tip) { tip = document.createElement("div"); tip.className = "ff-tip"; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip); }
    root.addEventListener("pointerover", (e) => {
      const el = e.target.closest("[data-tip]"); if (!el) return;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(() => {
        tip.textContent = el.dataset.tip;
        const r = el.getBoundingClientRect();
        tip.style.left = Math.max(8, Math.min(innerWidth - tip.offsetWidth - 8, r.left + r.width / 2 - tip.offsetWidth / 2)) + "px";
        tip.style.top = (r.bottom + 8 + tip.offsetHeight > innerHeight ? r.top - tip.offsetHeight - 8 : r.bottom + 8) + "px";
        tip.classList.add("open");
      }, tip.classList.contains("open") ? 0 : 350);
    });
    root.addEventListener("pointerout", (e) => { if (e.target.closest("[data-tip]")) { clearTimeout(tipTimer); tip.classList.remove("open"); } });
  }

  // ---- popover: a button toggles a .ff-pop; Escape and an outside click close it --------------------------------
  function popover(button, pop) {
    const close = () => { pop.classList.remove("open"); button.setAttribute("aria-expanded", "false"); };
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !pop.classList.contains("open");
      document.querySelectorAll(".ff-pop.open").forEach((p) => p !== pop && p.classList.remove("open"));
      pop.classList.toggle("open", open); button.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (e) => { if (!pop.contains(e.target)) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    return { close };
  }

  // ---- dialog and toast -----------------------------------------------------------------------------------------
  function dialog(scrim) {
    const close = () => scrim.classList.remove("open");
    scrim.addEventListener("click", (e) => { if (e.target === scrim || e.target.closest("[data-close]")) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    return { open: () => { scrim.classList.add("open"); const f = scrim.querySelector("button, [href], input"); if (f) f.focus(); }, close };
  }
  let toastEl = null, toastTimer = 0;
  function toast(text, ms = 2400) {
    if (!toastEl) { toastEl = document.createElement("div"); toastEl.className = "ff-toast"; toastEl.setAttribute("role", "status"); document.body.appendChild(toastEl); }
    toastEl.textContent = text; toastEl.classList.add("open");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove("open"), ms);
  }

  global.Fluid = { springCurve, fluidHover, segmented, tooltips, popover, dialog, toast };
})(window);
