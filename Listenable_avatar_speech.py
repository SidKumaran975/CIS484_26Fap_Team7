cd ~/CIS484_26Fap_Team7
source .venv/bin/activate

python <<'PY'
from pathlib import Path
from datetime import datetime
import shutil

page = Path("speech-to-text/index.html")
text = page.read_text()
marker = "<!-- examiner-audio-review -->"

if marker in text:
    raise SystemExit("Examiner audio replay is already installed.")

panel = """
<!-- examiner-audio-review -->
<section id="audioReview" class="card hidden"
         aria-labelledby="audioReviewHeading">
  <h2 id="audioReviewHeading" tabindex="-1">Examiner audio</h2>
  <p class="muted">
    Replay the AI examiner’s questions and follow-ups.
    Keep this page open to retain this list.
  </p>
  <ol id="audioReviewList"></ol>
</section>
"""

logic = """
const examinerAudioClips = [];

function rememberExaminerAudio(data, key) {
  if (!data.media_url || !data[key]) return;
  examinerAudioClips.push({
    prompt: data[key],
    url: data.media_url,
    question: data.question_number
  });
}

function showExaminerAudioReview() {
  videoEl.pause();
  videoEl.onended = null;
  const list = document.getElementById("audioReviewList");
  list.replaceChildren();

  examinerAudioClips.forEach((clip, index) => {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    const prompt = document.createElement("p");
    const player = document.createElement("audio");
    const error = document.createElement("p");

    item.style.cssText =
      "padding:16px 0;border-bottom:1px solid var(--line)";
    label.textContent =
      `Examiner turn ${index + 1} · Question ${clip.question}`;
    prompt.textContent = clip.prompt;
    prompt.style.whiteSpace = "pre-wrap";

    player.controls = true;
    player.preload = "none";
    player.src = clip.url;
    player.style.width = "100%";
    player.setAttribute(
      "aria-label", `Examiner audio, turn ${index + 1}`
    );

    error.className = "muted hidden";
    error.textContent =
      "This recording could not be loaded from the server.";

    player.addEventListener("error", () => {
      error.classList.remove("hidden");
    });
    player.addEventListener("play", () => {
      videoEl.pause();
      list.querySelectorAll("audio").forEach(other => {
        if (other !== player) other.pause();
      });
    });

    item.append(label, prompt, player, error);
    list.append(item);
  });

  if (!examinerAudioClips.length) {
    const empty = document.createElement("li");
    empty.textContent =
      "No examiner recordings were available for this attempt.";
    list.append(empty);
  }

  document.getElementById("audioReview").classList.remove("hidden");
  document.getElementById("audioReviewHeading").focus();
}
"""

edits = [
    (
        "</main>",
        panel + "\n</main>"
    ),
    (
        "function setPrompt(data,key){",
        logic +
        "\nfunction setPrompt(data,key){rememberExaminerAudio(data,key);"
    ),
    (
        "sessionId=data.session_id;",
        "sessionId=data.session_id;"
        "examinerAudioClips.length=0;"
        'document.getElementById("audioReview").classList.add("hidden");'
    ),
    (
        'statusEl.textContent="Complete.";',
        'statusEl.textContent="Complete. Listen to the examiner audio below.";',
    ),
    (
        "if(data.completed){",
        "if(data.completed){showExaminerAudioReview();"
    ),
]

for old, new in edits:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            "Your page differs from the expected version. "
            "Nothing was changed. Send this message: "
            f"{old!r} matched {count} times."
        )
    text = text.replace(old, new, 1)

backup = Path("local-backups") / (
    "examiner-audio-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
)
backup.mkdir(parents=True)
shutil.copy2(page, backup / "index.html")
page.write_text(text)

print("Installed examiner audio replay.")
print("Original page saved at:", backup / "index.html")
PY
