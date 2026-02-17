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
    const nextButton = document.querySelector("[data-rotate-next]");
    if (panels.length <= 1) {
      if (nextButton) {
        nextButton.hidden = true;
      }
      return;
    }

    const seconds = Number(shell.dataset.rightRotationSeconds || "60");
    const intervalMs = Math.max(seconds, 5) * 1000;
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

    const stopRotation = () => {
      if (timerId) {
        window.clearInterval(timerId);
        timerId = null;
      }
    };

    const showNextPanel = () => {
      activeIndex = (activeIndex + 1) % panels.length;
      showActivePanel();
    };

    const restartRotationTimer = () => {
      stopRotation();
      timerId = window.setInterval(showNextPanel, intervalMs);
    };

    const startRotation = () => {
      stopRotation();

      if (desktopBreakpoint.matches) {
        if (nextButton) {
          nextButton.hidden = true;
        }
        return;
      }

      if (nextButton) {
        nextButton.hidden = false;
      }
      showActivePanel();
      restartRotationTimer();
    };

    if (nextButton) {
      nextButton.addEventListener("click", () => {
        if (desktopBreakpoint.matches) {
          return;
        }
        showNextPanel();
        restartRotationTimer();
      });
    }

    startRotation();
    if (desktopBreakpoint.addEventListener) {
      desktopBreakpoint.addEventListener("change", startRotation);
    } else {
      desktopBreakpoint.addListener(startRotation);
    }
  };

  const initPhotoRotation = () => {
    const rotators = Array.from(document.querySelectorAll("[data-photo-rotator]"));
    if (rotators.length === 0) {
      return;
    }

    rotators.forEach((rotator) => {
      if (rotator.dataset.photoRotationInitialized === "true") {
        return;
      }
      rotator.dataset.photoRotationInitialized = "true";

      const slides = Array.from(rotator.querySelectorAll("[data-photo-slide]"));
      if (slides.length === 0) {
        return;
      }

      const caption = rotator.querySelector("[data-photo-caption]");
      const rotationSeconds = Number(rotator.dataset.photoRotationSeconds || "120");
      const intervalSeconds = Number.isFinite(rotationSeconds)
        ? Math.max(rotationSeconds, 5)
        : 120;
      let activeIndex = Math.max(
        0,
        slides.findIndex((slide) => slide.classList.contains("is-active")),
      );

      const render = () => {
        slides.forEach((slide, index) => {
          const isActive = index === activeIndex;
          slide.classList.toggle("is-active", isActive);
          slide.setAttribute("aria-hidden", isActive ? "false" : "true");
        });

        if (caption) {
          const activeSlide = slides[activeIndex];
          const activeCaption = activeSlide.dataset.caption;
          caption.textContent =
            activeCaption && activeCaption.trim().length > 0
              ? activeCaption
              : `Photo ${activeIndex + 1} of ${slides.length}`;
        }
      };

      render();
      if (slides.length <= 1) {
        return;
      }

      const rotate = () => {
        if (!rotator.isConnected) {
          return;
        }
        activeIndex = (activeIndex + 1) % slides.length;
        render();
        window.setTimeout(rotate, intervalSeconds * 1000);
      };

      window.setTimeout(rotate, intervalSeconds * 1000);
    });
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
  initPhotoRotation();
  initModalEvents();

  document.body.addEventListener("htmx:afterSwap", () => {
    initPhotoRotation();
  });
})();
