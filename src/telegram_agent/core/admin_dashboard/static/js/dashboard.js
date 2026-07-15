(function () {
  function initTabs(root) {
    // Scope to direct structure so nested [data-tabs] do not steal parent clicks.
    const list = root.querySelector(":scope > .tab-list");
    if (!list) {
      return;
    }
    const buttons = list.querySelectorAll(":scope > .tab");
    const panels = root.querySelectorAll(":scope > .tab-panel");
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const name = button.getAttribute("data-tab");
        buttons.forEach((b) => b.classList.toggle("active", b === button));
        panels.forEach((panel) => {
          panel.classList.toggle(
            "active",
            panel.getAttribute("data-panel") === name
          );
        });
      });
    });
  }

  document.querySelectorAll("[data-tabs]").forEach(initTabs);
})();
