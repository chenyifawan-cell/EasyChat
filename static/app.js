const fields = ["outline", "characters", "chapters", "style"];
const generationParamFields = ["targetWords", "maxRevisions", "recentChapterCount", "temperature"];
const generationParamDefaults = {
  targetWords: 3000,
  maxRevisions: 1,
  recentChapterCount: 3,
  temperature: 0.75,
};
const maxTargetWords = 20000;
let activeJobId = "";
let pollTimer = 0;
let latestPlan = null;

const $ = (id) => document.getElementById(id);

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

async function loadProject() {
  const data = await requestJson("/api/project");
  for (const key of fields) {
    $(key).value = data[key] || "";
  }
  loadGenerationParams();
  renderProfileSelect();
}

async function saveProject() {
  const payload = {};
  for (const key of fields) {
    payload[key] = $(key).value;
  }
  await requestJson("/api/project", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  saveGenerationParams();
  setStatus("设定已保存");
}

async function startGenerate() {
  await saveProject();
  const apiConfig = getSelectedProfile();
  if (!apiConfig) {
    throw new Error("请先进入 API 配置页保存一个模型配置。");
  }
  const payload = {
    ...collectGenerationParams(),
    ...apiConfig,
  };
  const data = await requestJson("/api/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  activeJobId = data.jobId;
  $("generateBtn").disabled = true;
  $("stopBtn").disabled = false;
  setStatus("生成任务已开始");
  switchTab("generateTab");
  pollStatus();
}

async function generatePlan() {
  const apiConfig = getSelectedProfile();
  if (!apiConfig) {
    throw new Error("请先进入 API 配置页保存一个模型配置。");
  }

  const text = $("plannerInput").value.trim();
  if (!text) {
    throw new Error("请先输入你想写的小说想法。");
  }
  setStatus("正在让 AI 整理设定...");
  $("plannerSendBtn").disabled = true;

  try {
    const currentProject = {};
    for (const key of fields) {
      currentProject[key] = $(key).value;
    }
    const data = await requestJson("/api/plan", {
      method: "POST",
      body: JSON.stringify({
        ...apiConfig,
        messages: [{ role: "user", content: text }],
        currentProject,
      }),
    });
    latestPlan = data.plan;
    renderPlanPreview(data.plan);
    setStatus("设定已生成，可一键导入。");
  } finally {
    $("plannerSendBtn").disabled = false;
  }
}

async function stopGenerate() {
  if (!activeJobId) return;
  await requestJson(`/api/stop/${activeJobId}`, { method: "POST" });
  $("stopBtn").disabled = true;
  setStatus("已请求暂停，当前章节结束后会停下");
}

async function pollStatus() {
  window.clearTimeout(pollTimer);
  if (!activeJobId) return;

  try {
    const job = await requestJson(`/api/status/${activeJobId}`);
    const percent = job.total ? Math.round((job.current / job.total) * 100) : 0;
    $("progressBar").style.width = `${percent}%`;
    setStatus(job.error || job.message || "生成中");
    $("logs").textContent = (job.logs || []).join("\n");

    if (["done", "error", "stopped"].includes(job.status)) {
      $("generateBtn").disabled = false;
      $("stopBtn").disabled = true;
      if (job.status === "done") {
        await loadOutput();
      }
      return;
    }
  } catch (error) {
    setStatus(error.message);
  }

  pollTimer = window.setTimeout(pollStatus, 1500);
}

async function loadOutput() {
  const data = await requestJson("/api/output");
  if (!data.exists || !data.novel) {
    $("output").value = "";
    setStatus("还没有成稿。请先点击“开始生成”，生成完成后再查看或下载。");
    return null;
  }
  $("output").value = data.novel || "";
  setStatus(`已加载成稿：${data.path}`);
  return data;
}

async function downloadOutput() {
  const data = await loadOutput();
  if (!data) return;
  const blob = new Blob([data.novel], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "novel.md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus("Markdown 已开始下载");
}

function setStatus(text) {
  $("statusText").textContent = text;
}

function collectGenerationParams() {
  return {
    targetWords: clampNumber($("targetWords").value, 500, maxTargetWords, generationParamDefaults.targetWords),
    maxRevisions: clampNumber($("maxRevisions").value, 0, 3, generationParamDefaults.maxRevisions),
    recentChapterCount: clampNumber($("recentChapterCount").value, 0, 10, generationParamDefaults.recentChapterCount),
    temperature: clampNumber($("temperature").value, 0, 1.5, generationParamDefaults.temperature),
  };
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(Math.max(number, min), max);
}

function saveGenerationParams() {
  const params = collectGenerationParams();
  for (const [key, value] of Object.entries(params)) {
    $(key).value = value;
  }
  localStorage.setItem("easyNovelGenerationParams", JSON.stringify(params));
}

function loadGenerationParams() {
  const saved = JSON.parse(localStorage.getItem("easyNovelGenerationParams") || "{}");
  const params = { ...generationParamDefaults, ...saved };
  for (const key of generationParamFields) {
    if ($(key)) $(key).value = params[key];
  }
  saveGenerationParams();
}

function setMaxTargetWords() {
  $("targetWords").value = maxTargetWords;
  saveGenerationParams();
  setStatus(`每章目标字数已设为最大：${maxTargetWords}`);
}

function renderPlanPreview(plan) {
  $("planPreview").textContent = formatPlan(plan);
}

function formatPlan(plan) {
  if (!plan) return "";
  return [
    "【故事大纲】",
    plan.outline || "",
    "",
    "【人物设定】",
    plan.characters || "",
    "",
    "【章节目录】",
    plan.chapters || "",
    "",
    "【写作风格】",
    plan.style || "",
  ].join("\n").trim();
}

async function importPlan() {
  if (!latestPlan) {
    throw new Error("还没有可导入的设定，请先生成设定。");
  }
  for (const key of fields) {
    if (latestPlan[key] !== undefined) {
      $(key).value = latestPlan[key] || "";
    }
  }
  await saveProject();
  setStatus("AI 设定已导入并保存。");
  switchTab("settingsTab");
}

function clearPlanner() {
  latestPlan = null;
  $("plannerInput").value = "";
  $("planPreview").textContent = "生成后会在这里预览大纲、人物设定和章节目录。";
  setStatus("AI 设定助手已清空。");
}

function switchTab(tabId) {
  for (const button of document.querySelectorAll(".tab-button")) {
    button.classList.toggle("active", button.dataset.tab === tabId);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.id === tabId);
  }
}

function loadProfiles() {
  return JSON.parse(localStorage.getItem("easyNovelApiProfiles") || "[]");
}

function renderProfileSelect() {
  const profiles = loadProfiles();
  const select = $("profileSelect");
  select.innerHTML = "";

  if (!profiles.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "未配置";
    select.appendChild(option);
    $("profileInfo").textContent = "请先到配置页保存一个模型配置。";
    return;
  }

  for (const profile of profiles) {
    const option = document.createElement("option");
    option.value = profile.profileName;
    option.textContent = `${profile.profileName} · ${profile.model}`;
    select.appendChild(option);
  }

  const savedName = localStorage.getItem("easyNovelSelectedProfile");
  if (savedName && profiles.some((profile) => profile.profileName === savedName)) {
    select.value = savedName;
  }
  updateProfileInfo();
}

function getSelectedProfile() {
  const name = $("profileSelect").value;
  return loadProfiles().find((profile) => profile.profileName === name);
}

function updateProfileInfo() {
  const profile = getSelectedProfile();
  if (!profile) {
    $("profileInfo").textContent = "请先到配置页保存一个模型配置。";
    return;
  }
  localStorage.setItem("easyNovelSelectedProfile", profile.profileName);
  $("profileInfo").textContent = `${profile.apiStyle} · ${profile.model} · 推理深度：${profile.reasoningDepth || "none"}`;
}

$("saveBtn").addEventListener("click", () => saveProject().catch((error) => setStatus(error.message)));
$("generateBtn").addEventListener("click", () => startGenerate().catch((error) => {
  $("generateBtn").disabled = false;
  $("stopBtn").disabled = true;
  setStatus(error.message);
}));
$("stopBtn").addEventListener("click", () => stopGenerate().catch((error) => setStatus(error.message)));
$("loadOutputBtn").addEventListener("click", () => loadOutput().catch((error) => setStatus(error.message)));
$("downloadBtn").addEventListener("click", () => downloadOutput().catch((error) => setStatus(error.message)));
$("profileSelect").addEventListener("change", updateProfileInfo);
$("maxWordsBtn").addEventListener("click", setMaxTargetWords);
generationParamFields.forEach((key) => {
  $(key).addEventListener("change", saveGenerationParams);
  $(key).addEventListener("blur", saveGenerationParams);
});
$("plannerSendBtn").addEventListener("click", () => generatePlan().catch((error) => setStatus(error.message)).finally(() => {
  $("plannerSendBtn").disabled = false;
}));
$("importPlanBtn").addEventListener("click", () => importPlan().catch((error) => setStatus(error.message)));
$("clearPlannerBtn").addEventListener("click", clearPlanner);
document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

loadProject().catch((error) => setStatus(error.message));
