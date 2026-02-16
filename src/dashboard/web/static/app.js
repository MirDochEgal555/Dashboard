(() => {
  const shell = document.querySelector(".dashboard-shell");
  const modalRoot = document.getElementById("modal-root");
  const clockValue = document.getElementById("clock-value");
  const clockDate = document.getElementById("clock-date");

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
    if (!shell || window.matchMedia("(max-width: 980px)").matches) {
      return;
    }

    const panels = Array.from(document.querySelectorAll(".rotating-panel"));
    if (panels.length <= 1) {
      return;
    }

    const seconds = Number(shell.dataset.rightRotationSeconds || "60");
    let activeIndex = panels.findIndex((panel) => panel.classList.contains("is-active"));
    if (activeIndex < 0) {
      activeIndex = 0;
      panels[0].classList.add("is-active");
    }

    window.setInterval(() => {
      panels[activeIndex].classList.remove("is-active");
      activeIndex = (activeIndex + 1) % panels.length;
      panels[activeIndex].classList.add("is-active");
    }, seconds * 1000);
  };

  const closeModal = () => {
    if (modalRoot) {
      modalRoot.innerHTML = "";
    }
  };

  const initModalEvents = () => {
    document.addEventListener("click", async (event) => {
      const openTrigger = event.target.closest("[data-open-modal]");
      if (openTrigger) {
        const widgetName = openTrigger.getAttribute("data-open-modal");
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
        return;
      }

      if (event.target.closest("[data-close-modal]")) {
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

