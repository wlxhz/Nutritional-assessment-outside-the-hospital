const state = {
  user: null,
  profile: null,
  plan: null,
  report: null,
  rangeType: "day",
};

const $ = (id) => document.getElementById(id);

const mealNames = {
  breakfast: "早餐",
  lunch: "午餐",
  dinner: "晚餐",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.feedback || "请求失败");
  }
  return data;
}

function setFeedback(id, message, isError = false) {
  const node = $(id);
  if (!node) return;
  node.textContent = message || "";
  node.style.color = isError ? "#c82727" : "#4f774d";
}

function phone() {
  return $("phoneInput").value.trim();
}

function renderDevState(config = {}) {
  $("devState").innerHTML = `
    <dt>运行方式</dt><dd>${config.runtime || "local"}</dd>
    <dt>本地存储</dt><dd>${config.storage || "sqlite"}</dd>
    <dt>AI 令牌</dt><dd>${config.aiConfigured ? "已配置" : "未配置，使用本地占位"}</dd>
    <dt>视觉接口</dt><dd>${config.vision?.status || "reserved"}</dd>
  `;
}

function showMainApp() {
  $("onboarding").classList.remove("active");
  document.querySelectorAll(".screen").forEach((screen) => screen.classList.remove("active"));
  $("gardenScreen").classList.add("active");
  document.querySelectorAll(".tabbar button").forEach((btn) => btn.classList.remove("active"));
  document.querySelector('[data-screen="gardenScreen"]').classList.add("active");
  $("screenTitle").textContent = "花园";
}

function userId() {
  return state.user?.user_id || state.user?.userId;
}

async function sendCode() {
  try {
    const data = await api("/api/mmy/auth/sms-code/send", {
      method: "POST",
      body: JSON.stringify({ phone: phone() }),
    });
    $("codeInput").value = data.demoCode || "";
    setFeedback("authFeedback", `${data.feedback} 有效期 ${data.expiresInSeconds}s。`);
  } catch (error) {
    setFeedback("authFeedback", error.message, true);
  }
}

async function smsLogin() {
  try {
    const data = await api("/api/mmy/auth/sms-code/login", {
      method: "POST",
      body: JSON.stringify({ phone: phone(), code: $("codeInput").value.trim() }),
    });
    state.user = data.user;
    $("loginState").textContent = `已登录 ${state.user.phone}`;
    setFeedback("authFeedback", "登录成功，请保存身体指征。");
  } catch (error) {
    setFeedback("authFeedback", error.message, true);
  }
}

async function oneTapLogin() {
  try {
    const data = await api("/api/mmy/auth/phone-one-tap", {
      method: "POST",
      body: JSON.stringify({ phone: phone(), carrier: "三大运营商" }),
    });
    state.user = data.user;
    $("loginState").textContent = `已登录 ${state.user.phone}`;
    setFeedback("authFeedback", data.feedback);
  } catch (error) {
    setFeedback("authFeedback", error.message, true);
  }
}

function collectProfile() {
  return {
    userId: userId(),
    diseaseType: $("diseaseType").value,
    diseaseOtherText: $("diseaseOtherText").value.trim(),
    weight: Number($("weight").value || 0),
    height: Number($("height").value || 0),
    age: Number($("age").value || 0),
    gender: $("gender").value,
    allergyHistory: $("allergyHistory").value.trim(),
    diseaseHistory: $("diseaseHistory").value.trim(),
    workIntensity: $("workIntensity").value,
    emergencyContactName: "紧急联系人",
    emergencyContactPhone: $("emergencyPhone").value.trim(),
  };
}

async function saveProfileAndGenerate() {
  if (!state.user) {
    setFeedback("profileFeedback", "请先登录。", true);
    return;
  }
  try {
    const profilePayload = collectProfile();
    const profileData = await api("/api/mmy/user/profile", {
      method: "POST",
      body: JSON.stringify(profilePayload),
    });
    state.profile = profileData.profile;
    const planData = await api("/api/mmy/nutrition-plans/generate", {
      method: "POST",
      body: JSON.stringify({ userId: userId() }),
    });
    state.plan = planData.plan;
    renderPlan();
    await createSeedIntake();
    await refreshGarden();
    await refreshReport();
    await refreshAgentPrompts();
    setFeedback("profileFeedback", "已保存，并生成营养方案。");
    showMainApp();
  } catch (error) {
    setFeedback("profileFeedback", error.message, true);
  }
}

function renderPlan() {
  const plan = state.plan?.plan || {};
  const daily = plan.dailyGoal || {};
  $("aiStatus").textContent = state.plan?.aiStatus === "model" ? "AI 已生成" : "本地占位";
  $("planSummary").innerHTML = `
    <p>${daily.summary || "等待生成营养方案。"}</p>
    <div class="metric-grid">
      <div class="metric"><span>能量</span><strong>${daily.energyKcal || 0} kcal</strong></div>
      <div class="metric"><span>蛋白质</span><strong>${daily.proteinG || 0} g</strong></div>
      <div class="metric"><span>脂肪</span><strong>${daily.fatG || 0} g</strong></div>
      <div class="metric"><span>碳水</span><strong>${daily.carbohydrateG || 0} g</strong></div>
    </div>
  `;
  const meals = plan.mealBreakdown || [];
  $("mealTabs").innerHTML = meals.map((meal) => `
    <article class="meal-card">
      <strong>${mealNames[meal.mealType] || meal.name || meal.mealType}</strong>
      <span>${meal.energyKcal || 0} kcal</span><br />
      <span>蛋白质 ${meal.proteinG || 0}g</span>
    </article>
  `).join("");
}

async function createSeedIntake() {
  await api("/api/mmy/intake-records", {
    method: "POST",
    body: JSON.stringify({
      userId: userId(),
      mealType: "breakfast",
      items: [
        {
          itemName: "燕麦粥",
          itemType: "food",
          grams: 180,
          complianceLevel: "compliant",
          nutrients: { energyKcal: 216, proteinG: 7.2, fatG: 3.6, carbohydrateG: 28.8 },
        },
        {
          itemName: "鸡蛋",
          itemType: "food",
          grams: 55,
          complianceLevel: "generally_compliant",
          nutrients: { energyKcal: 78, proteinG: 6.5, fatG: 5.4, carbohydrateG: 0.6 },
        },
      ],
    }),
  });
}

async function refreshGarden() {
  if (!state.user) return;
  const data = await api(`/api/mmy/garden/progress?userId=${encodeURIComponent(userId())}`);
  $("gardenDays").innerHTML = data.days.map((day) => `
    <div class="day-cell ${day.smallFlowerEarned ? "done" : ""}">
      <span>第 ${day.dayIndex} 天</span>
      <strong>${day.smallFlowerEarned ? "小花" : "待养"}</strong>
    </div>
  `).join("");
  $("bigFlower").textContent = data.bigFlowerEarned ? "大花" : "花";
}

async function loadVisionContract() {
  try {
    const data = await api("/api/mmy/vision/contract");
    const box = $("visionContract");
    box.textContent = JSON.stringify(data.expectedResult, null, 2);
    box.classList.toggle("active");
  } catch (error) {
    $("visionContract").textContent = error.message;
    $("visionContract").classList.add("active");
  }
}

function showRisk() {
  $("riskAlert").classList.remove("hidden");
}

async function openSmsFlow() {
  if (!state.profile?.emergencyContactPhone) {
    alert("请先填写紧急联系人手机号。");
    return;
  }
  const ok = window.confirm("将拉起系统短信界面，由用户手动确认发送。是否继续？");
  if (!ok) return;
  const data = await api("/api/mmy/sms/confirm", {
    method: "POST",
    body: JSON.stringify({
      contact: { phone: state.profile.emergencyContactPhone },
      message: "慢慢养提醒：检测到红色风险食物，请关注饮食方案。",
    }),
  });
  window.location.href = data.smsUrl;
}

async function refreshReport() {
  if (!state.user) return;
  const data = await api(`/api/mmy/reports/nutrients?userId=${encodeURIComponent(userId())}&rangeType=${state.rangeType}`);
  state.report = data.report;
  renderPie(data.data.pieChartData || []);
  renderBars(data.data.barChartData || []);
}

function renderPie(items) {
  const colors = ["#8aa87f", "#dfc66a", "#c98265", "#9eb7c7"];
  let cursor = 0;
  const stops = items.map((item, index) => {
    const start = cursor;
    cursor += Number(item.percent || 0);
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  });
  $("pieChart").style.background = `conic-gradient(${stops.join(", ") || "#eadfce 0 100%"})`;
}

function renderBars(items) {
  $("barChart").innerHTML = items.map((item) => {
    const pct = Math.min(100, Math.round((Number(item.actualValue || 0) / Math.max(1, Number(item.targetValue || 1))) * 100));
    return `
      <div class="bar-row">
        <span>${item.label}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <span>${pct}%</span>
      </div>
    `;
  }).join("");
}

async function refreshAgentPrompts() {
  if (!state.user) return;
  const data = await api(`/api/mmy/agent/prompts?userId=${encodeURIComponent(userId())}`);
  $("agentMessages").innerHTML = (data.prompts || []).map((prompt) => `
    <div class="message agent">${prompt.content}</div>
  `).join("");
}

async function sendAgentMessage() {
  const content = $("agentInput").value.trim();
  if (!content || !state.user) return;
  $("agentInput").value = "";
  const data = await api("/api/mmy/agent/messages", {
    method: "POST",
    body: JSON.stringify({ userId: userId(), content, messageType: "recipe_feedback" }),
  });
  const messages = $("agentMessages");
  for (const msg of data.messages || []) {
    const div = document.createElement("div");
    div.className = `message ${msg.sender}`;
    div.textContent = msg.content;
    messages.appendChild(div);
  }
  messages.scrollTop = messages.scrollHeight;
}

function switchScreen(target) {
  $("onboarding").classList.remove("active");
  document.querySelectorAll(".screen").forEach((screen) => screen.classList.remove("active"));
  $(target).classList.add("active");
  document.querySelectorAll(".tabbar button").forEach((btn) => btn.classList.toggle("active", btn.dataset.screen === target));
  $("screenTitle").textContent = document.querySelector(`[data-screen="${target}"]`).textContent;
}

function bindEvents() {
  $("sendCodeBtn").addEventListener("click", sendCode);
  $("loginBtn").addEventListener("click", smsLogin);
  $("oneTapBtn").addEventListener("click", oneTapLogin);
  $("saveProfileBtn").addEventListener("click", saveProfileAndGenerate);
  $("visionContractBtn").addEventListener("click", loadVisionContract);
  $("riskBtn").addEventListener("click", showRisk);
  $("smsBtn").addEventListener("click", openSmsFlow);
  $("agentSendBtn").addEventListener("click", sendAgentMessage);
  $("agentInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendAgentMessage();
  });
  document.querySelectorAll(".tabbar button").forEach((button) => {
    button.addEventListener("click", () => switchScreen(button.dataset.screen));
  });
  document.querySelectorAll("#rangeTabs button").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll("#rangeTabs button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.rangeType = button.dataset.range;
      await refreshReport();
    });
  });
}

async function init() {
  bindEvents();
  renderPie([]);
  renderBars([
    { label: "能量", actualValue: 0, targetValue: 1600 },
    { label: "蛋白质", actualValue: 0, targetValue: 65 },
    { label: "脂肪", actualValue: 0, targetValue: 45 },
    { label: "碳水", actualValue: 0, targetValue: 210 },
  ]);
  try {
    renderDevState(await api("/api/mmy/config"));
  } catch (error) {
    renderDevState({ runtime: "offline", storage: "unknown", vision: { status: "unknown" } });
  }
  $("gardenDays").innerHTML = Array.from({ length: 7 }, (_, index) => `
    <div class="day-cell"><span>第 ${index + 1} 天</span><strong>待养</strong></div>
  `).join("");
}

init();
