(() => {
  const nav = document.querySelector(".screen-links");
  const tabs = Array.from(nav.querySelectorAll("a"));
  const panels = tabs.map(tab => document.getElementById(tab.hash.slice(1)));
  const indexFromUrl = () => Math.max(0, tabs.findIndex(tab => tab.hash === location.hash));

  function select(index) {
    tabs.forEach((tab, i) => {
      const active = i === index;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      panels[i].hidden = !active;
    });
  }

  nav.setAttribute("role", "tablist");
  tabs.forEach((tab, index) => {
    const panel = panels[index];
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", panel.id);
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", tab.id);
    panel.tabIndex = 0;
  });

  function activate(index) {
    select(index);
    if (location.hash !== tabs[index].hash) history.pushState(null, "", tabs[index].hash);
    tabs[index].focus({ preventScroll: true });
  }

  nav.addEventListener("click", event => {
    const tab = event.target.closest("a");
    if (!tab || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    activate(tabs.indexOf(tab));
  });

  nav.addEventListener("keydown", event => {
    const current = tabs.indexOf(event.target);
    if (current < 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const count = tabs.length;
    const keys = {
      ArrowRight: (current + 1) % count,
      ArrowLeft: (current + count - 1) % count,
      Home: 0,
      End: count - 1,
      " ": current,
      Enter: current,
    };
    if (!(event.key in keys)) return;
    event.preventDefault();
    activate(keys[event.key]);
  });

  select(indexFromUrl());
  window.addEventListener("popstate", () => select(indexFromUrl()));
  window.addEventListener("hashchange", () => select(indexFromUrl()));
})();
