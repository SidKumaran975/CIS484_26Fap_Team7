python <<'PY'
from pathlib import Path
from datetime import datetime
import shutil

pages = [
    Path("faculty-portal/login.html"),
    Path("faculty-portal/index.html"),
    Path("faculty-portal/report.html"),
    Path("speech-to-text/index.html"),
    Path("speech-to-text/admin.html"),
]

marker = "<!-- keyboard-accessibility-local-v1 -->"

addition = r'''
<!-- keyboard-accessibility-local-v1 -->
<style>
:focus-visible {
  outline: 3px solid #ffdf9c !important;
  outline-offset: 3px !important;
}
.keyboard-skip {
  position: fixed;
  top: 10px;
  left: 10px;
  z-index: 1000;
  transform: translateY(-200%);
  padding: 12px 18px;
  background: white;
  color: #101820;
  border-radius: 6px;
  font: bold 16px system-ui;
}
.keyboard-skip:focus { transform: none; }
.keyboard-instructions {
  padding: 10px 16px;
  margin: 0;
  background: #101820;
  color: white;
  font: 13px/1.5 system-ui;
}
.switch input:focus-visible + .slider {
  outline: 3px solid #ffdf9c !important;
  outline-offset: 3px;
}
.modal-backdrop { overflow-y: auto; }
.modal {
  max-height: calc(100dvh - 40px);
  overflow-y: auto;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    scroll-behavior: auto !important;
  }
}
@media print {
  .keyboard-skip, .keyboard-instructions { display: none; }
}
</style>
<script>
document.addEventListener("DOMContentLoaded", () => {
  const main = document.querySelector("main") ||
    document.querySelector(".role-panel") ||
    document.querySelector("h1");

  if (main) {
    if (!main.id) main.id = "keyboard-main";
    main.tabIndex = -1;

    const skip = document.createElement("a");
    skip.className = "keyboard-skip";
    skip.href = "#" + main.id;
    skip.textContent = "Skip to main content";
    skip.onclick = () => main.focus();
    document.body.prepend(skip);
  }

  const help = document.createElement("p");
  help.className = "keyboard-instructions";
  help.textContent =
    "Keyboard: Tab / Shift+Tab to move; Enter or Space for " +
    "buttons; arrow keys for course tabs; Escape to close dialogs.";
  if (main) main.prepend(help);

  const visible = element =>
    element.getClientRects().length > 0;

  const controls = modal =>
    [...modal.querySelectorAll(
      "button, input, select, textarea, a[href], [tabindex]"
    )].filter(element =>
      !element.disabled && element.tabIndex >= 0 &&
      visible(element) && !element.closest("[inert]")
    );

  const stack = [];
  const origins = new Map();
  const inertBefore = new Map();

  function updateBackground() {
    inertBefore.forEach((value, element) => {
      element.inert = value;
    });
    inertBefore.clear();

    const top = stack.at(-1);
    if (!top) return;

    [...document.body.children].forEach(element => {
      if (element !== top && !element.contains(top) &&
          !["SCRIPT", "STYLE"].includes(element.tagName)) {
        inertBefore.set(element, element.inert);
        element.inert = true;
      }
    });
  }

  // Preserve the application's existing open/close behavior.
  if (typeof window.openModal === "function" &&
      typeof window.closeModal === "function") {
    const originalOpen = window.openModal;
    const originalClose = window.closeModal;

    window.openModal = function(id) {
      const modal = document.getElementById(id);
      if (!modal) return originalOpen(id);

      if (!stack.includes(modal)) {
        origins.set(modal, document.activeElement);
        stack.push(modal);
      }

      originalOpen(id);
      updateBackground();

      const dialog = modal.querySelector(
        '[role="dialog"], [role="alertdialog"]'
      ) || modal;
      dialog.tabIndex = -1;
      (controls(modal)[0] || dialog).focus();
    };

    window.closeModal = function(id) {
      const modal = document.getElementById(id);
      originalClose(id);

      const index = stack.indexOf(modal);
      if (index < 0) return;
      stack.splice(index, 1);
      updateBackground();

      const origin = origins.get(modal);
      origins.delete(modal);

      if (origin?.isConnected && !origin.disabled &&
          visible(origin) && !origin.closest("[inert]")) {
        origin.focus();
      } else if (stack.length) {
        controls(stack.at(-1))[0]?.focus();
      } else {
        main?.focus();
      }
    };

    document.addEventListener("keydown", event => {
      const modal = stack.at(-1);
      if (!modal) return;

      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.closeModal(modal.id);
      }

      if (event.key === "Tab") {
        const items = controls(modal);
        const first = items[0], last = items.at(-1);
        if (!first) {
          event.preventDefault();
          return;
        }

        const active = document.activeElement;
        if (event.shiftKey &&
            (active === first || !items.includes(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey &&
                   (active === last || !items.includes(active))) {
          event.preventDefault();
          first.focus();
        }
      }
    }, true);
  }

  const tabs = [...document.querySelectorAll("[data-tab]")];

  function updateTabs() {
    tabs.forEach(tab => {
      const selected = tab.classList.contains("active");
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;

      const panel = document.getElementById(
        "tab-" + tab.dataset.tab
      );
      if (panel) {
        tab.id = tab.id || "keyboard-tab-" + tab.dataset.tab;
        tab.setAttribute("aria-controls", panel.id);
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", tab.id);
        panel.tabIndex = 0;
      }
    });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", updateTabs);
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"]
          .includes(event.key)) return;

      event.preventDefault();
      const next = event.key === "Home" ? 0 :
        event.key === "End" ? tabs.length - 1 :
        (index + (event.key === "ArrowRight" ? 1 : -1) +
         tabs.length) % tabs.length;

      tabs[next].click();
      tabs[next].focus();
    });
  });
  updateTabs();

  document.querySelectorAll(
    "#status, #msg, #toast, #transcriptsStatus"
  ).forEach(element => {
    if (!element.hasAttribute("role"))
      element.setAttribute("role", "status");
    if (!element.hasAttribute("aria-live"))
      element.setAttribute("aria-live", "polite");
  });

  document.querySelectorAll(".table-wrap").forEach(element => {
    element.tabIndex = 0;
    element.setAttribute("role", "region");
    element.setAttribute("aria-label", "Scrollable table");
  });

  // Keep focus useful when a question's controls are replaced.
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-act]");
    const row = button?.closest(".q");
    const box = document.getElementById("questions");
    if (!row || !box) return;

    const index = [...box.children].indexOf(row);
    const action = button.dataset.act;

    requestAnimationFrame(() => {
      if (button.isConnected ||
          document.activeElement !== document.body) return;

      const replacement = box.children[
        Math.min(index, box.children.length - 1)
      ];
      const target = replacement?.querySelector(
        `[data-act="${action}"]`
      ) || document.getElementById("approveAllBtn");
      target?.focus();
    });
  }, true);

  // Move focus to Stop when recording starts.
  const stop = document.getElementById("stop");
  if (stop) {
    new MutationObserver(() => {
      if (!stop.disabled) stop.focus();
    }).observe(stop, {
      attributes: true,
      attributeFilter: ["disabled"]
    });
  }
});
</script>
'''

updates = []

for page in pages:
    if not page.is_file():
        raise SystemExit(
            f"Missing {page}. Check your project folder. "
            "No files were changed."
        )

    text = page.read_text()

    if marker in text or "/accessibility/keyboard.js" in text:
        print("Already installed; skipped:", page)
        continue

    if text.count("</head>") != 1:
        raise SystemExit(
            f"Unexpected page format: {page}. "
            "No files were changed."
        )

    updates.append((
        page,
        text.replace("</head>", addition + "\n</head>", 1)
    ))

if updates:
    backup = Path("local-backups") / (
        "keyboard-" +
        datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )

    for page, _ in updates:
        destination = backup / page
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(page, destination)

    try:
        for page, updated in updates:
            page.write_text(updated)
    except Exception:
        for page, _ in updates:
            shutil.copy2(backup / page, page)
        raise

    print("\nKeyboard support installed.")
    print("Original pages backed up to:", backup)
else:
    print("\nKeyboard support is already installed.")
PY
