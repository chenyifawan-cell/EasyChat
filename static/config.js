const profileFields = ["profileName", "apiStyle", "baseUrl", "model", "apiKey", "maxTokens", "timeout", "reasoningDepth", "anthropicVersion"];
const $cfg = (id) => document.getElementById(id);
const defaultsByStyle = {
  chat: { baseUrl: "https://api.openai.com/v1", model: "gpt-4.1-mini" },
  responses: { baseUrl: "https://api.openai.com/v1", model: "gpt-4.1-mini" },
  anthropic: { baseUrl: "https://api.anthropic.com/v1", model: "claude-sonnet-4-5" },
};

function setStatus(text) {
  $cfg("statusText").textContent = text;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

function loadProfiles() {
  return JSON.parse(localStorage.getItem("easyNovelApiProfiles") || "[]");
}

function saveProfiles(profiles) {
  localStorage.setItem("easyNovelApiProfiles", JSON.stringify(profiles));
}

function collectProfile() {
  return {
    profileName: $cfg("profileName").value.trim() || "默认配置",
    apiStyle: $cfg("apiStyle").value,
    baseUrl: $cfg("baseUrl").value.trim(),
    model: $cfg("model").value.trim(),
    apiKey: $cfg("apiKey").value.trim(),
    maxTokens: Number($cfg("maxTokens").value || 8192),
    timeout: Number($cfg("timeout").value || 180),
    reasoningDepth: $cfg("reasoningDepth").value,
    anthropicVersion: $cfg("anthropicVersion").value.trim() || "2023-06-01",
  };
}

function fillForm(profile) {
  $cfg("profileName").value = profile.profileName || "默认配置";
  $cfg("apiStyle").value = profile.apiStyle || "chat";
  $cfg("baseUrl").value = profile.baseUrl || defaultsByStyle.chat.baseUrl;
  $cfg("model").value = profile.model || defaultsByStyle.chat.model;
  $cfg("apiKey").value = profile.apiKey || "";
  $cfg("maxTokens").value = profile.maxTokens || 8192;
  $cfg("timeout").value = profile.timeout || 180;
  $cfg("reasoningDepth").value = profile.reasoningDepth || "none";
  $cfg("anthropicVersion").value = profile.anthropicVersion || "2023-06-01";
  updateStyle();
}

function updateStyle() {
  const style = $cfg("apiStyle").value;
  const defaults = defaultsByStyle[style] || defaultsByStyle.chat;
  if (!$cfg("baseUrl").value) $cfg("baseUrl").value = defaults.baseUrl;
  if (!$cfg("model").value) $cfg("model").value = defaults.model;
  $cfg("anthropicVersionField").hidden = style !== "anthropic";
}

function renderProfiles() {
  const profiles = loadProfiles();
  const root = $cfg("profileList");
  root.innerHTML = "";

  if (!profiles.length) {
    root.innerHTML = '<p class="muted">还没有保存任何配置。</p>';
    return;
  }

  for (const profile of profiles) {
    const row = document.createElement("div");
    row.className = "profile-row";
    row.innerHTML = `
      <div>
        <strong>${profile.profileName || "默认配置"}</strong>
        <span>${profile.apiStyle || "chat"} · ${profile.model || ""}</span>
      </div>
      <div class="row-actions">
        <button type="button" data-load="${profile.profileName}">使用</button>
        <button type="button" data-delete="${profile.profileName}">删除</button>
      </div>
    `;
    root.appendChild(row);
  }
}

function upsertProfile(profile) {
  const profiles = loadProfiles();
  const index = profiles.findIndex((item) => item.profileName === profile.profileName);
  if (index >= 0) profiles[index] = profile;
  else profiles.unshift(profile);
  saveProfiles(profiles);
  renderProfiles();
}

function deleteProfile(name) {
  saveProfiles(loadProfiles().filter((item) => item.profileName !== name));
  renderProfiles();
}

async function saveProfile() {
  const profile = collectProfile();
  upsertProfile(profile);
  setStatus("配置已保存");
}

async function testProfile() {
  const profile = collectProfile();
  const data = await requestJson("/api/test-config", {
    method: "POST",
    body: JSON.stringify(profile),
  });
  setStatus(`测试成功：${data.reply}`);
}

async function fetchModels() {
  const profile = collectProfile();
  const data = await requestJson("/api/models", {
    method: "POST",
    body: JSON.stringify(profile),
  });
  setStatus(`已获取 ${data.models.length} 个模型`);
  const current = $cfg("model").value.trim();
  const list = data.models || [];
  if (list.length) {
    const chosen = current && list.includes(current) ? current : list[0];
    $cfg("model").value = chosen;
  }
  renderModelList(data.models || []);
}

function renderModelList(models) {
  const root = $cfg("logs");
  if (!models.length) {
    root.textContent = "没有拉到模型。";
    return;
  }
  root.innerHTML = "";
  for (const model of models) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "model-pill";
    button.textContent = model;
    button.addEventListener("click", () => {
      $cfg("model").value = model;
      setStatus(`已选择模型：${model}`);
    });
    root.appendChild(button);
  }
}

$cfg("saveBtn").addEventListener("click", () => saveProfile().catch((error) => setStatus(error.message)));
$cfg("testBtn").addEventListener("click", () => testProfile().catch((error) => setStatus(error.message)));
$cfg("fetchModelsBtn").addEventListener("click", () => fetchModels().catch((error) => setStatus(error.message)));
$cfg("apiStyle").addEventListener("change", updateStyle);
$cfg("profileList").addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const loadName = target.getAttribute("data-load");
  const deleteName = target.getAttribute("data-delete");
  if (loadName) {
    const profile = loadProfiles().find((item) => item.profileName === loadName);
    if (profile) fillForm(profile);
  }
  if (deleteName) deleteProfile(deleteName);
});

const firstProfile = loadProfiles()[0];
fillForm(firstProfile || { profileName: "默认配置" });
renderProfiles();
