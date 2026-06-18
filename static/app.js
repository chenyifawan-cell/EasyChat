const fields = ["outline", "characters", "chapters", "style"];
let activeJobId = "";
let pollTimer = 0;

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
  setStatus("设定已保存");
}

async function startGenerate() {
  await saveProject();
  const apiConfig = getSelectedProfile();
  if (!apiConfig) {
    throw new Error("请先进入 API 配置页保存一个模型配置。");
  }
  const payload = {
    targetWords: Number($("targetWords").value || 3000),
    maxRevisions: Number($("maxRevisions").value || 1),
    temperature: Number($("temperature").value || 0.75),
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
  pollStatus();
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

loadProject().catch((error) => setStatus(error.message));
