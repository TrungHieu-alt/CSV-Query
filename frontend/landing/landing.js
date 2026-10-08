(() => {
  const sheet = document.getElementById("landing-sheet");
  const experience = document.getElementById("experience");
  const reveal = document.getElementById("app-reveal");
  const preview = document.getElementById("app-preview");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const appUrl = new URL(preview.dataset.src, window.location.href);
  let start = 0;
  let distance = 1;
  let ticking = false;
  let loaded = false;
  let navigating = false;
  let fallbackTimer;

  function openApp() {
    if (navigating) return;
    navigating = true;
    window.location.assign(appUrl.href);
  }
  function loadPreview() {
    if (preview.hasAttribute("src")) return;
    preview.src = appUrl.href;
    // A CDN delaying the preview must not trap users at the end of the scroll.
    fallbackTimer = window.setTimeout(() => { loaded = true; render(); }, 5000);
  }
  function measure() {
    const height = sheet.offsetHeight;
    start = Math.max(0, height - window.innerHeight);
    distance = Math.max(420, window.innerHeight * .9);
    experience.style.height = `${height + distance}px`;
    sheet.style.setProperty("--sticky-top", `${-start}px`);
    schedule();
  }
  function render() {
    ticking = false;
    const progress = Math.max(0, Math.min(1, (window.scrollY - start) / distance));
    const eased = progress * progress * (3 - 2 * progress);
    sheet.style.opacity = String(1 - eased);
    sheet.style.transform = `translateY(${-72 * eased}px)`;
    sheet.style.filter = `blur(${3.5 * eased}px)`;
    reveal.style.opacity = String(eased);
    reveal.style.transform = `translateY(${24 * (1 - eased)}px)`;
    sheet.inert = progress > .98;
    if (progress > .02) loadPreview();
    if (progress >= .999 && loaded) openApp();
  }
  function schedule() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(render);
  }
  preview.addEventListener("load", () => {
    if (!preview.hasAttribute("src")) return;
    loaded = true;
    window.clearTimeout(fallbackTimer);
    reveal.classList.add("ready");
    schedule();
  });
  document.querySelectorAll("[data-enter]").forEach(link => {
    link.addEventListener("click", event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      if (reduceMotion.matches) return;
      event.preventDefault();
      document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close());
      loadPreview();
      window.scrollTo({ top: start + distance, behavior: "smooth" });
    });
  });
  document.querySelectorAll("[data-dialog]").forEach(button => {
    button.addEventListener("click", () => document.getElementById(button.dataset.dialog).showModal());
  });
  document.querySelectorAll("dialog").forEach(dialog => {
    dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
  });
  const toggle = document.getElementById("demo-toggle");
  toggle.addEventListener("click", () => {
    const table = document.getElementById("table-demo");
    const showTable = table.hidden;
    table.hidden = !showTable;
    document.getElementById("chart-demo").hidden = showTable;
    toggle.setAttribute("aria-pressed", String(showTable));
    toggle.textContent = showTable ? "View as chart ↔" : "View as table ↔";
  });
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", measure);
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  window.addEventListener("pageshow", () => {
    navigating = false;
    window.scrollTo(0, 0);
    measure();
  });
  new ResizeObserver(measure).observe(sheet);
  document.fonts.ready.then(measure);
  measure();
})();
