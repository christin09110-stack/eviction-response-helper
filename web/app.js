// Mobile console for the eviction response helper. Voice input (Web Speech
// API) degrades to the always-present typed input; voice output degrades to
// the always-visible answer text. Nothing here files anything -- every
// network call either reads back a citation, a deadline, or a prepared
// referral for the person to act on themselves.

function getUserId() {
  try {
    let id = localStorage.getItem("uid");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("uid", id);
    }
    return id;
  } catch {
    // Private browsing / storage blocked: a per-tab id still lets the
    // session work, it just will not persist across reloads.
    return crypto.randomUUID();
  }
}

const USER_ID = getUserId();
let lastAnswerStyle = "plain";

const $ = (id) => document.getElementById(id);

// Presentation-only day count for the hero: the backend's app.deadlines
// already computed the deadline date and put it in reply.data.deadline; this
// just re-expresses that same date as "N days left" for the headline number.
// It duplicates no legal logic -- it is calendar subtraction on a date the
// server already produced.
function daysUntil(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const deadlineUTC = Date.UTC(y, m - 1, d);
  const now = new Date();
  const todayUTC = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((deadlineUTC - todayUTC) / 86400000);
}

function showHeroDeadline(isoDate, deadlineSentence) {
  $("hero-pending").hidden = true;
  $("hero-active").hidden = false;
  $("deadline-text").textContent = deadlineSentence;

  const remaining = daysUntil(isoDate);
  const numberEl = $("hero-days-number");
  const labelEl = $("hero-days-label");
  if (remaining <= 0) {
    numberEl.textContent = "Today";
    labelEl.textContent = "is the deadline";
  } else {
    numberEl.textContent = String(remaining);
    labelEl.textContent = remaining === 1 ? "day left" : "days left";
  }
  numberEl.classList.toggle("is-urgent", remaining <= 2);
}

function resetHero() {
  $("hero-pending").hidden = false;
  $("hero-active").hidden = true;
}

const ANSWER_ICON_GROUNDED =
  '<path d="M7 8h10M7 12h7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>' +
  '<path d="M4.5 5.5h15v10h-6l-3.5 3v-3h-5.5v-10Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>';
const ANSWER_ICON_REFUSAL =
  '<circle cx="12" cy="12" r="8.2" fill="none" stroke="currentColor" stroke-width="1.7"/>' +
  '<path d="M6.7 6.7l10.6 10.6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>';

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${url} responded ${response.status}`);
  return response.json();
}

const photoPicker = document.querySelector(".photo-picker");
$("photo").addEventListener("focus", () => photoPicker.classList.add("is-focused"));
$("photo").addEventListener("blur", () => photoPicker.classList.remove("is-focused"));

$("photo").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const status = $("photo-status");
  status.textContent = "Reading your summons…";

  const form = new FormData();
  form.append("user_id", USER_ID);
  form.append("photo", file);

  let reply;
  try {
    const response = await fetch("/api/case", { method: "POST", body: form });
    if (!response.ok) throw new Error(`/api/case responded ${response.status}`);
    reply = await response.json();
  } catch {
    status.textContent = "Could not reach the server. Check your connection and try again.";
    return;
  }

  $("halt-card").hidden = true;
  $("draft-card").hidden = true;

  if (reply.kind === "retake") {
    resetHero();
    status.textContent = reply.text;
  } else if (reply.kind === "halt") {
    resetHero();
    status.textContent = "";
    $("halt-text").textContent = reply.text;
    $("halt-card").hidden = false;
  } else if (reply.kind === "case_started") {
    status.textContent = "Summons read successfully.";
    showHeroDeadline(reply.data.deadline, reply.text);
    $("draft-status").textContent = "";
    $("draft-card").hidden = false;
  } else {
    resetHero();
    status.textContent = reply.text || "Something unexpected happened. Please try again.";
  }
});

$("draft").addEventListener("click", async () => {
  const status = $("draft-status");
  const defendantName = $("defendant-name").value.trim();
  if (!defendantName) {
    status.textContent = "Enter your name before preparing the draft.";
    return;
  }

  const payload = {
    user_id: USER_ID,
    defendant_name: defendantName,
    reported_disrepair: $("reported-disrepair").checked,
    landlord_notified: $("landlord-notified").checked,
    complained_on: $("complained-on").value || null,
    notice_served_on: $("notice-served-on").value || null,
    rent_accepted_after_notice: $("rent-accepted-after-notice").checked,
    notice_defective: $("notice-defective").checked,
  };

  status.textContent = "Preparing your draft…";

  let response;
  try {
    response = await fetch("/api/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    status.textContent = "Could not reach the server. Check your connection and try again.";
    return;
  }

  if (!response.ok) {
    status.textContent = response.status === 404
      ? "Photograph your summons first (step 1) so there is a case to draft against."
      : "Could not prepare the draft. Please try again.";
    return;
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "UD-105-draft.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);

  status.textContent = "Draft downloaded — this is not filed. Review every line, then file it yourself.";
});

$("send").addEventListener("click", async () => {
  const question = $("q").value.trim();
  if (!question) return;

  let reply;
  try {
    reply = await postJSON("/api/ask", { user_id: USER_ID, question });
  } catch {
    $("answer-text").textContent = "Could not reach the server. Check your connection and try again.";
    $("answer-cites").textContent = "";
    $("answer-panel").classList.remove("is-refusal");
    $("answer-heading").textContent = "Answer";
    $("answer-icon").innerHTML = ANSWER_ICON_GROUNDED;
    $("answer").hidden = false;
    return;
  }

  lastAnswerStyle = (reply.data && reply.data.style) || "plain";
  $("answer-text").textContent = reply.text;
  const citations = (reply.data && reply.data.citations) || [];
  $("answer-cites").textContent = citations.length ? `Source: ${citations.join("; ")}` : "";

  // The refusal state matters as much as a correct answer: this tool would
  // rather say nothing than guess. grounded === false means answer_question
  // found no citation it could stand behind (see app.answering.REFUSAL) --
  // that gets its own considered presentation, not error styling.
  const grounded = !reply.data || reply.data.grounded !== false;
  $("answer-panel").classList.toggle("is-refusal", !grounded);
  $("answer-heading").textContent = grounded ? "Answer" : "I don't have a citation for that";
  $("answer-icon").innerHTML = grounded ? ANSWER_ICON_GROUNDED : ANSWER_ICON_REFUSAL;

  $("feedback-status").textContent = "";
  $("answer").hidden = false;
});

$("play").addEventListener("click", () => {
  if (!("speechSynthesis" in window)) return;
  const text = $("answer-text").textContent;
  if (!text) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
});

$("speak").addEventListener("click", () => {
  const status = $("speech-status");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    status.textContent = "Voice input is not available in this browser — please type your question.";
    return;
  }
  const recognition = new Recognition();
  recognition.lang = "en-US";
  status.textContent = "Listening…";
  recognition.onresult = (event) => {
    $("q").value = event.results[0][0].transcript;
    status.textContent = "";
  };
  recognition.onerror = () => {
    status.textContent = "Could not hear that — please type your question instead.";
  };
  recognition.onend = () => {
    if (status.textContent === "Listening…") status.textContent = "";
  };
  recognition.start();
});

for (const button of document.querySelectorAll(".feedback-btn")) {
  button.addEventListener("click", async () => {
    const landed = button.dataset.landed === "true";
    try {
      await postJSON("/api/feedback", { user_id: USER_ID, style: lastAnswerStyle, landed });
      $("feedback-status").textContent = "Thanks — noted for next time.";
    } catch {
      $("feedback-status").textContent = "Could not save that, but thank you for the feedback.";
    }
  });
}
