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

  function initWorkflowPoller(container) {
    const url = container.getAttribute("data-poll-url");
    const interval = Number(container.getAttribute("data-poll-interval-ms")) || 10000;
    if (!url) {
      return;
    }

    let stopped = false;
    let timer = null;

    function workflowTabIsActive() {
      const panel = container.closest('[data-panel="workflows"]');
      return Boolean(panel && panel.classList.contains("active"));
    }

    function schedule() {
      if (!stopped) {
        timer = window.setTimeout(refresh, interval);
      }
    }

    async function refresh() {
      timer = null;
      if (document.hidden || !workflowTabIsActive()) {
        schedule();
        return;
      }
      try {
        const response = await window.fetch(url, {
          credentials: "same-origin",
          headers: { "X-Requested-With": "workflow-poller" },
        });
        if (!response.ok || response.redirected || response.url.endsWith("/login")) {
          throw new Error(`Workflow refresh returned ${response.status}`);
        }
        container.innerHTML = await response.text();
        container.classList.remove("is-stale");
        const fragment = container.querySelector("[data-poll-needed]");
        if (fragment && fragment.getAttribute("data-poll-needed") === "false") {
          stopped = true;
          return;
        }
      } catch (_error) {
        container.classList.add("is-stale");
      }
      schedule();
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !stopped && timer === null) {
        schedule();
      }
    });
    schedule();
  }

  document.querySelectorAll("[data-workflow-poller]").forEach(initWorkflowPoller);
})();
