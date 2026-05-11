(function () {
  const header = document.querySelector("[data-site-header]");
  const navToggle = document.querySelector(".nav-toggle");
  const nav = document.querySelector(".site-nav");
  const revealEls = Array.from(document.querySelectorAll(".reveal"));

  function setScrolledState() {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 12);
  }

  function closeNav() {
    document.body.classList.remove("nav-open");
    header?.classList.remove("nav-active");
    navToggle?.setAttribute("aria-expanded", "false");
  }

  setScrolledState();
  window.addEventListener("scroll", setScrolledState, { passive: true });

  navToggle?.addEventListener("click", () => {
    const isOpen = document.body.classList.toggle("nav-open");
    header?.classList.toggle("nav-active", isOpen);
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  nav?.addEventListener("click", (event) => {
    if (event.target instanceof HTMLAnchorElement) {
      closeNav();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeNav();
    }
  });

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const targetId = button.getAttribute("data-copy-target");
      const target = targetId ? document.getElementById(targetId) : null;
      const text = target?.innerText.trim();
      if (!text || !navigator.clipboard) return;

      const originalLabel = button.textContent;
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
        window.setTimeout(() => {
          button.textContent = originalLabel;
        }, 1500);
      } catch {
        button.textContent = "Select";
      }
    });
  });

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.1 }
    );

    revealEls.forEach((el) => observer.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add("is-visible"));
  }
})();
