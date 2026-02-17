(() => {
  const shell = document.querySelector(".dashboard-shell");
  const modalRoot = document.getElementById("modal-root");
  const clockValue = document.getElementById("clock-value");
  const clockDate = document.getElementById("clock-date");
  const desktopBreakpoint = window.matchMedia("(max-width: 980px)");

  const updateClock = () => {
    if (!clockValue || !clockDate) {
      return;
    }
    const now = new Date();
    clockValue.textContent = now.toLocaleTimeString();
    clockDate.textContent = now.toLocaleDateString(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
  };

  const initClock = () => {
    updateClock();
    window.setInterval(updateClock, 1000);
  };

  const initRightPanelRotation = () => {
    if (!shell) {
      return;
    }

    const panels = Array.from(document.querySelectorAll(".rotating-panel"));
    if (panels.length <= 1) {
      return;
    }

    const seconds = Number(shell.dataset.rightRotationSeconds || "60");
    let activeIndex = Math.max(
      0,
      panels.findIndex((panel) => panel.classList.contains("is-active")),
    );
    let timerId = null;

    const showActivePanel = () => {
      panels.forEach((panel, index) => {
        panel.classList.toggle("is-active", index === activeIndex);
      });
    };

    const startRotation = () => {
      if (timerId) {
        window.clearInterval(timerId);
        timerId = null;
      }

      if (desktopBreakpoint.matches) {
        return;
      }

      showActivePanel();
      timerId = window.setInterval(() => {
        activeIndex = (activeIndex + 1) % panels.length;
        showActivePanel();
      }, seconds * 1000);
    };

    startRotation();
    if (desktopBreakpoint.addEventListener) {
      desktopBreakpoint.addEventListener("change", startRotation);
    } else {
      desktopBreakpoint.addListener(startRotation);
    }
  };

  const closeModal = () => {
    if (modalRoot) {
      modalRoot.innerHTML = "";
    }
  };

  const openModal = async (widgetName) => {
    if (!widgetName || !modalRoot) {
      return;
    }
    try {
      const response = await fetch(`/modals/${widgetName}`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) {
        throw new Error(`Failed to load modal for ${widgetName}`);
      }
      modalRoot.innerHTML = await response.text();
    } catch (error) {
      console.error(error);
    }
  };

  const initModalEvents = () => {
    document.addEventListener("click", async (event) => {
      const openTrigger = event.target.closest("[data-open-modal]");
      if (openTrigger) {
        const widgetName = openTrigger.getAttribute("data-open-modal");
        await openModal(widgetName);
        return;
      }

      if (event.target.closest("[data-close-modal]")) {
        closeModal();
        return;
      }

      if (event.target.matches("[data-modal-backdrop]")) {
        closeModal();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeModal();
      }
    });
  };

  initClock();
  initRightPanelRotation();
  initModalEvents();
})();
