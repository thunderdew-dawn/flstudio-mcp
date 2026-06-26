(function () {
  const mediaItems = {
    gain: {
      title: "Mix Review & Gain Staging",
      description: "Ask for a safe mix scan, understand the top risks and approve only the next reversible step.",
      src: "assets/ai-apply-gain-staging-example.gif",
      fallback: "https://raw.githubusercontent.com/thunderdew-dawn/fls-pilot/v3/alpha/site/assets/ai-apply-gain-staging-example.gif",
      alt: "fls-pilot gain staging AI workflow preview",
      caption: "AI-assisted gain-staging workflow preview."
    },
    routing: {
      title: "Routing Audit",
      description: "Let your AI review buses, sends and fragile routing decisions with local FL Studio context.",
      src: "assets/ai-based-mixer-routing-example.gif",
      fallback: "https://raw.githubusercontent.com/thunderdew-dawn/fls-pilot/v3/alpha/site/assets/ai-based-mixer-routing-example.gif",
      alt: "fls-pilot routing audit AI workflow preview",
      caption: "AI-based mixer routing workflow preview."
    },
    organizer: {
      title: "Project Organizer",
      description: "Use AI-assisted cleanup for colors, names and structure without losing control of the project.",
      src: "assets/ai-color-my-tracks-example.gif",
      fallback: "https://raw.githubusercontent.com/thunderdew-dawn/fls-pilot/v3/alpha/site/assets/ai-color-my-tracks-example.gif",
      alt: "fls-pilot project organizer AI workflow preview",
      caption: "AI-assisted project organization workflow preview."
    },
    eq: {
      title: "Plugin & EQ Workflows",
      description: "Plan safe high-pass and cleanup passes with knowledgebase-backed ranges instead of guessed plugin values.",
      src: "assets/ai-set-highpass-on-eq-batch-example.gif",
      fallback: "https://raw.githubusercontent.com/thunderdew-dawn/fls-pilot/v3/alpha/site/assets/ai-set-highpass-on-eq-batch-example.gif",
      alt: "fls-pilot EQ batch workflow preview",
      caption: "AI-assisted high-pass EQ batch workflow preview."
    },
    composition: {
      title: "Composition Workflow",
      description: "Use AI as a local creative assistant while keeping production decisions and project safety in your hands.",
      src: "assets/ai-generate-bassline-example.gif",
      fallback: "https://raw.githubusercontent.com/thunderdew-dawn/fls-pilot/v3/alpha/site/assets/ai-generate-bassline-example.gif",
      alt: "fls-pilot composition workflow preview",
      caption: "AI-assisted bassline generation workflow preview."
    }
  };

  const menuButton = document.querySelector("[data-menu-button]");
  const menu = document.querySelector("[data-menu]");
  if (menuButton && menu) {
    menuButton.addEventListener("click", () => {
      const isOpen = menu.classList.toggle("open");
      menuButton.setAttribute("aria-expanded", String(isOpen));
    });
    menu.addEventListener("click", (event) => {
      if (event.target.matches("a")) {
        menu.classList.remove("open");
        menuButton.setAttribute("aria-expanded", "false");
      }
    });
  }

  const setFallbacks = () => {
    document.querySelectorAll("img[data-fallback-src]").forEach((img) => {
      img.addEventListener("error", () => {
        const fallback = img.getAttribute("data-fallback-src");
        if (fallback && img.src !== fallback) {
          img.src = fallback;
        }
      }, { once: true });
    });
  };

  const setupMediaTabs = () => {
    const tabs = Array.from(document.querySelectorAll("[data-media-target]"));
    const title = document.querySelector("[data-media-title]");
    const description = document.querySelector("[data-media-description]");
    const image = document.querySelector("[data-media-image]");
    const caption = document.querySelector("[data-media-caption]");

    if (!tabs.length || !title || !description || !image || !caption) return;

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const key = tab.getAttribute("data-media-target");
        const item = mediaItems[key];
        if (!item) return;

        tabs.forEach((other) => {
          const isActive = other === tab;
          other.classList.toggle("active", isActive);
          other.setAttribute("aria-selected", String(isActive));
        });

        title.textContent = item.title;
        description.textContent = item.description;
        image.src = item.src;
        image.setAttribute("data-fallback-src", item.fallback);
        image.alt = item.alt;
        caption.textContent = item.caption;
      });
    });
  };

  const setupCopyButtons = () => {
    document.querySelectorAll("[data-copy]").forEach((button) => {
      button.addEventListener("click", async () => {
        const text = button.getAttribute("data-copy") || "";
        try {
          await navigator.clipboard.writeText(text);
          button.textContent = "Copied";
          button.classList.add("copied");
          window.setTimeout(() => {
            button.textContent = "Copy";
            button.classList.remove("copied");
          }, 1800);
        } catch (error) {
          button.textContent = "Select text";
        }
      });
    });
  };

  const setupReveal = () => {
    const nodes = document.querySelectorAll(".reveal");
    if (!nodes.length) return;

    if (!("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("is-visible"));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });

    nodes.forEach((node) => observer.observe(node));
  };

  const setupActiveNav = () => {
    const links = Array.from(document.querySelectorAll(".site-menu a[href^='#']"));
    const sections = links
      .map((link) => document.querySelector(link.getAttribute("href")))
      .filter(Boolean);

    if (!sections.length || !("IntersectionObserver" in window)) return;

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        links.forEach((link) => {
          link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`);
        });
      });
    }, { threshold: 0.38 });

    sections.forEach((section) => observer.observe(section));
  };

  const setupSafetyTicker = () => {
    const steps = Array.from(document.querySelectorAll(".timeline-step"));
    if (!steps.length) return;

    let index = 0;
    window.setInterval(() => {
      steps.forEach((step, stepIndex) => step.classList.toggle("active", stepIndex === index));
      index = (index + 1) % steps.length;
    }, 2600);
  };

  document.addEventListener("DOMContentLoaded", () => {
    setFallbacks();
    setupMediaTabs();
    setupCopyButtons();
    setupReveal();
    setupActiveNav();
    setupSafetyTicker();
  });
})();
