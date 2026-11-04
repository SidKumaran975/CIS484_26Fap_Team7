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
missing = [str(p) for p in pages if not p.is_file()]
if missing:
    raise SystemExit("Missing files: " + ", ".join(missing))

marker = "<!-- color-blind-mode-local -->"
snippet = r'''
<!-- color-blind-mode-local -->
<style>
.cb-toolbar{display:flex;justify-content:flex-end;padding:10px 16px;
background:#101820;border-bottom:1px solid #8796a5}
#cb-toggle{min-height:44px;padding:10px 14px;border:2px solid #a6cfff;
border-radius:8px;background:#162c43;color:white;
font:700 14px system-ui;cursor:pointer}
#cb-toggle[aria-pressed="true"]{background:#ffcb70;color:#101820}
#cb-toggle:focus-visible{outline:3px solid white;outline-offset:3px}
html.cb-mode{
--bg:#101820;--panel:#172330;--panel-2:#223344;--panel-3:#2a4054;
--text:#f5f7fa;--muted:#c2ced9;--line:#8796a5;
--purple:#3071ad;--purple-bright:#3071ad;--purple-deep:#194b78;
--bright:#3071ad;--deep:#194b78;--gold:#ffcb70;
--success:#89c8ff;--warning:#ffcb70;--danger:#ffcb70}
html.cb-mode body{background:#101820}
html.cb-mode :focus-visible{outline:3px solid #ffdf9c;outline-offset:3px}
html.cb-mode .badge.green,html.cb-mode .s-met{
background:#173b59;color:#b8dfff;border:2px solid #89c8ff}
html.cb-mode .badge.red,html.cb-mode .s-not_met,
html.cb-mode .btn.danger{
background:#3b2c14;color:#ffdf9c;border:2px dashed #ffcb70}
html.cb-mode .badge.gold,html.cb-mode .s-partial{
background:#303030;color:white;border:3px double #e3e8ed}
html.cb-mode .badge.purple{
background:#20364b;color:#d4eaff;border-color:#89c8ff}
html.cb-mode .dot.ok{background:#89c8ff;border-radius:0;box-shadow:none}
html.cb-mode .dot.bad{background:#ffcb70;box-shadow:none}
html.cb-mode #start{background:#89c8ff;color:#101820}
html.cb-mode #stop{background:#ffcb70;color:#101820;
border:2px dashed #101820}
html.cb-mode #status.recording{
color:#ffdf9c;border:2px dashed #ffcb70;background:#3b2c14}
@media print{.cb-toolbar{display:none}}
</style>
<script>
(() => {
  const key = "oral-exam-color-blind";
  const read = () => document.cookie.split("; ")
    .some(value => value === key + "=on");
  let enabled = read();
  let button;
  function apply() {
    document.documentElement.classList.toggle("cb-mode", enabled);
    if (button) {
      button.setAttribute("aria-pressed", String(enabled));
      button.textContent = "Color-blind mode: " + (enabled ? "On" : "Off");
    }
  }
  apply();
  document.addEventListener("DOMContentLoaded", () => {
    // Avoid duplicating the toggle if the shared version is installed.
    if (document.getElementById("color-blind-toggle")) return;
    const bar = document.createElement("div");
    bar.className = "cb-toolbar";
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", "Display accessibility");
    button = document.createElement("button");
    button.id = "cb-toggle";
    button.type = "button";
    button.onclick = () => {
      enabled = !enabled;
      document.cookie = key + "=" + (enabled ? "on" : "off") +
        "; Path=/; Max-Age=31536000; SameSite=Lax";
      apply();
    };
    bar.append(button);
    document.body.prepend(bar);
    apply();
  });
  window.addEventListener("focus", () => {
    enabled = read();
    apply();
  });
})();
</script>
'''

changes = []
for page in pages:
    text = page.read_text()
    if marker in text or '/accessibility/accessibility.js' in text:
        print("Already installed; skipped:", page)
        continue
    if "</head>" not in text:
        raise SystemExit("Cannot locate </head> in " + str(page))
    changes.append((page, text.replace("</head>", snippet + "\n</head>", 1)))

if changes:
    backup = Path("local-backups") / (
        "color-blind-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    for page, updated in changes:
        destination = backup / page
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(page, destination)
        page.write_text(updated)
        print("Updated:", page)
    print("Original pages backed up to:", backup)
else:
    print("No changes needed.")
PY
