(function () {
  function initTabs(root) {
    const buttons = root.querySelectorAll(".tab");
    const panels = root.querySelectorAll(".tab-panel");
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
