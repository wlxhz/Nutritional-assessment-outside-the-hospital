const state = {
  user: null,
  profile: null,
  plan: null,
  report: null,
  rangeType: "day",
  visionFrameResolution: "1280x720",
  vision: {
    session: null,
    sessionState: null,
    report: null,
    syncedRecord: null,
    pollTimer: null,
    latestFoods: [],
    latestFrameSrc: "",
    latestFrameDataUrl: "",
  },
};

const STORAGE_KEY = "mmyLocalSession";
const $ = (id) => document.getElementById(id);

const mealNames = {
  breakfast: "早餐",
  lunch: "午餐",
  dinner: "晚餐",
};

const qualityLabels = [
  ["angle_coverage", "视角覆盖"],
  ["depth_completeness", "深度完整度"],
  ["mask_stability", "主体稳定"],
  ["motion_quality", "连续采集"],
  ["lighting", "光照"],
  ["blur", "清晰度"],
  ["plate_visibility", "可见度"],
];

const complianceMeta = {
  compliant: { label: "符合", className: "compliant" },
  generally_compliant: { label: "一般符合", className: "generally" },
  non_compliant: { label: "非常不符合", className: "risk" },
};

const stickerStroke = {
  compliant: "#9DCF55",
  generally_compliant: "#EFD67C",
  non_compliant: "#C82727",
};

let stickerThumbUid = 0;

function escapeHtml(value = "") {
  return `${value ?? ""}`.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function validComplianceLevel(level) {
  return ["compliant", "generally_compliant", "non_compliant"].includes(level)
    ? level
    : "generally_compliant";
}

function safeStickerColor(color, fallback = "#EFD67C") {
  const value = `${color || ""}`.trim();
  return /^#[0-9a-fA-F]{6}$/.test(value) ? value : fallback;
}

function safeSvgPath(path, fallback) {
  const value = `${path || ""}`.trim();
  return value && /^[MmZzLlHhVvCcSsQqTtAa0-9,.\-\s]+$/.test(value) ? value : fallback;
}

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

function carrier() {
  return $("carrierSelect").value;
}

function persistSession() {
  if (!$("rememberLogin")?.checked || !state.user) return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    user: state.user,
    profile: state.profile,
    plan: state.plan,
    phone: state.user.phone || phone(),
    savedAt: Date.now(),
  }));
}

function clearPersistedSession() {
  localStorage.removeItem(STORAGE_KEY);
}

function updateLoginState() {
  const loggedIn = Boolean(state.user);
  $("loginState").textContent = loggedIn ? `已登录 ${state.user.phone}` : "未登录";
  $("logoutBtn")?.classList.toggle("hidden", !loggedIn);
}

function restoreSession() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return false;
  try {
    const saved = JSON.parse(raw);
    state.user = saved.user || null;
    state.profile = saved.profile || null;
    state.plan = saved.plan || null;
    if (!state.user) return false;
    $("phoneInput").value = saved.phone || state.user.phone || $("phoneInput").value;
    updateLoginState();
    if (state.profile?.emergencyContactPhone) $("emergencyPhone").value = state.profile.emergencyContactPhone;
    if (state.profile?.diseaseType) $("diseaseType").value = state.profile.diseaseType;
    toggleDiseaseOther();
    if (state.profile?.diseaseOtherText) $("diseaseOtherText").value = state.profile.diseaseOtherText;
    if (state.profile?.dietPreference) $("dietPreference").value = state.profile.dietPreference;
    if (state.plan) renderPlan();
    showMainApp();
    refreshLatestPlan();
    refreshGarden();
    refreshReport();
    refreshAgentPrompts();
    refreshIntakeStickers();
    return true;
  } catch {
    clearPersistedSession();
    return false;
  }
}

function logout() {
  stopVisionPolling();
  clearPersistedSession();
  state.user = null;
  state.profile = null;
  state.plan = null;
  state.report = null;
  state.vision.session = null;
  state.vision.sessionState = null;
  state.vision.report = null;
  state.vision.syncedRecord = null;
  state.vision.latestFoods = [];
  state.vision.latestFrameSrc = "";
  state.vision.latestFrameDataUrl = "";
  updateLoginState();
  $("onboarding").classList.add("active");
  document.querySelectorAll(".screen").forEach((screen) => screen.classList.remove("active"));
  document.querySelectorAll(".tabbar button").forEach((btn) => btn.classList.remove("active"));
  $("screenTitle").textContent = "花园";
  $("visionReportSummary")?.classList.add("hidden");
  $("visionSessionPanel")?.classList.add("hidden");
  $("visionRealtimePanel")?.classList.add("hidden");
  $("syncVisionBtn").disabled = true;
  $("finishVisionBtn").disabled = true;
  renderVisionFoods([]);
  renderPie([]);
  renderBars([
    { label: "能量", actualValue: 0, targetValue: 1600 },
    { label: "蛋白质", actualValue: 0, targetValue: 65 },
    { label: "脂肪", actualValue: 0, targetValue: 45 },
    { label: "碳水", actualValue: 0, targetValue: 210 },
  ]);
  $("planSummary").innerHTML = "";
  $("mealTabs").innerHTML = "";
  $("agentMessages").innerHTML = "";
  $("gardenFoodStickers").innerHTML = `<span class="empty-vision">今日还没有保存饮食贴纸</span>`;
  setFeedback("authFeedback", "已退出登录。");
}

function renderDevState(config = {}) {
  $("devState").innerHTML = `
    <dt>运行方式</dt><dd>${config.runtime || "local"}</dd>
    <dt>本地存储</dt><dd>${config.storage || "sqlite"}</dd>
    <dt>AI 模型</dt><dd>${config.aiConfigured ? `${config.ai?.defaultModel || "已配置"} 已配置` : "未配置，使用本地规则"}</dd>
    <dt>环境文件</dt><dd>${(config.loadedEnvFiles || []).length ? "已加载" : "未加载"}</dd>
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
      body: JSON.stringify({ phone: phone(), carrier: carrier() }),
    });
    $("codeInput").value = data.demoCode || "";
    setFeedback("authFeedback", `${data.feedback} 有效期 ${data.expiresInSeconds}s。请求号：${data.gateway?.requestId || "-"}`);
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
    updateLoginState();
    persistSession();
    setFeedback("authFeedback", "登录成功，请保存身体指征。");
  } catch (error) {
    setFeedback("authFeedback", error.message, true);
  }
}

async function oneTapLogin() {
  try {
    const data = await api("/api/mmy/auth/phone-one-tap", {
      method: "POST",
      body: JSON.stringify({ phone: phone(), carrier: carrier() }),
    });
    state.user = data.user;
    updateLoginState();
    persistSession();
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
    dietPreference: $("dietPreference").value.trim(),
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
    persistSession();
    renderPlan();
    await createSeedIntake();
    await refreshIntakeStickers();
    await refreshGarden();
    await refreshReport();
    await refreshAgentPrompts();
    setFeedback("profileFeedback", "已保存，并生成营养方案。");
    showMainApp();
  } catch (error) {
    setFeedback("profileFeedback", error.message, true);
  }
}

function toggleDiseaseOther() {
  const isOther = $("diseaseType").value === "other";
  $("diseaseOtherField").classList.toggle("hidden", !isOther);
  if (!isOther) $("diseaseOtherText").value = "";
}

function diseaseLabel(value = "") {
  return {
    diabetes: "糖尿病",
    hypertension: "高血压",
    internal_postoperative_recovery: "内科术后康复",
    tumor_recovery: "肿瘤康复",
    other: "其他",
  }[value] || value || "未填写";
}

function planBasisHtml(plan = {}) {
  const notes = plan.demoNotes || [];
  const profile = state.profile || {};
  const basis = [
    `病症：${diseaseLabel(profile.diseaseType)}${profile.diseaseOtherText ? `（${profile.diseaseOtherText}）` : ""}`,
    `身体数据：${profile.age || "-"}岁 / ${profile.weight || "-"}kg / ${profile.height || "-"}cm`,
    `饮食偏好：${profile.dietPreference || "未填写，按清淡均衡默认推荐"}`,
  ];
  return `
    <div class="plan-basis">
      ${basis.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
      ${notes.map((note) => `<span>${escapeHtml(note)}</span>`).join("")}
    </div>
  `;
}

function adjustmentHtml(plan = {}) {
  const adjustment = plan.latestAdjustment || {};
  const summary = adjustment.summary || [];
  const tags = adjustment.feedbackTags || [];
  const previous = adjustment.previousDailyGoal || {};
  const updated = adjustment.updatedDailyGoal || {};
  const metricChanges = [
    ["能量", "energyKcal", "kcal"],
    ["蛋白质", "proteinG", "g"],
    ["脂肪", "fatG", "g"],
    ["碳水", "carbohydrateG", "g"],
  ].filter(([, key]) => Number(previous[key] || 0) && Number(updated[key] || 0) && Number(previous[key]) !== Number(updated[key]));
  if (!adjustment.reason && !summary.length && !metricChanges.length) return "";
  return `
    <div class="adjustment-card">
      <div class="adjustment-head">
        <strong>本次 Agent 调整</strong>
        ${tags.length ? `<span>${tags.map((tag) => escapeHtml(tag)).join(" / ")}</span>` : ""}
      </div>
      ${adjustment.reason ? `<p>${escapeHtml(adjustment.reason)}</p>` : ""}
      ${summary.length ? `
        <div class="change-list">
          ${summary.map((change) => `
            <div>
              <b>${escapeHtml(mealNames[change.mealType] || change.name || change.mealType)}</b>
              ${change.removed?.length ? `<span>移除：${change.removed.map((item) => escapeHtml(item)).join("、")}</span>` : ""}
              ${change.added?.length ? `<span>新增：${change.added.map((item) => escapeHtml(item)).join("、")}</span>` : ""}
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${metricChanges.length ? `
        <div class="target-diff">
          ${metricChanges.map(([label, key, unit]) => `<span>${label} ${Math.round(previous[key])}${unit} → ${Math.round(updated[key])}${unit}</span>`).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function renderPlan() {
  const plan = state.plan?.plan || {};
  const daily = plan.dailyGoal || {};
  const sourceLabel = state.plan?.sourceType === "agent_adjusted" ? "Agent 已调整" : state.plan?.aiStatus === "model" ? "AI 真实生成" : "本地个性化";
  $("aiStatus").textContent = sourceLabel;
  $("planSummary").innerHTML = `
    <p>${escapeHtml(daily.summary || "等待生成营养方案。")}</p>
    <div class="metric-grid">
      <div class="metric"><span>能量</span><strong>${daily.energyKcal || 0} kcal</strong></div>
      <div class="metric"><span>蛋白质</span><strong>${daily.proteinG || 0} g</strong></div>
      <div class="metric"><span>脂肪</span><strong>${daily.fatG || 0} g</strong></div>
      <div class="metric"><span>碳水</span><strong>${daily.carbohydrateG || 0} g</strong></div>
    </div>
    ${planBasisHtml(plan)}
    ${adjustmentHtml(plan)}
  `;
  const meals = plan.mealBreakdown || [];
  const recipesByMeal = Object.fromEntries((plan.recipes || []).map((recipe) => [recipe.mealType, recipe]));
  $("mealTabs").innerHTML = meals.map((meal) => `
    <article class="meal-card">
      <strong>${escapeHtml(mealNames[meal.mealType] || meal.name || meal.mealType)}</strong>
      <span>${meal.energyKcal || 0} kcal</span><br />
      <span>蛋白质 ${meal.proteinG || 0}g / 碳水 ${meal.carbohydrateG || 0}g</span>
      <ul>${(meal.recommendedItems || recipesByMeal[meal.mealType]?.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      <small>${escapeHtml(meal.reason || recipesByMeal[meal.mealType]?.reason || "")}</small>
    </article>
  `).join("");
}

async function refreshLatestPlan() {
  if (!state.user) return;
  try {
    const data = await api(`/api/mmy/users/${encodeURIComponent(userId())}/nutrition-plan`);
    state.plan = data.plan;
    persistSession();
    renderPlan();
  } catch {
    renderPlan();
  }
}

function displayFoodName(food = {}) {
  const profileKey = food.profile_key || food.profileKey || food.visionMeta?.profileKey;
  if (profileKey === "pork_floss_pastry") return "肉松糕点";
  const name = `${food.name || food.itemName || ""}`;
  const category = food.category || food.visionMeta?.category;
  if (/炸制牛肉|炸制.*牛肉|牛肉/.test(name) && category === "甜点") return "肉松糕点";
  return name || "未命名食物";
}

function foodGrams(food = {}) {
  return Number([
    food.grams,
    food.weight_g,
    food.estimated_weight_g,
    food.meta?.grams,
  ].find((value) => Number.isFinite(Number(value)) && Number(value) > 0) || 0);
}

function foodCalories(food = {}) {
  const nutrition = nutrientsOfFood(food);
  return Number([
    food.caloriesKcal,
    food.calories_kcal,
    food.meta?.caloriesKcal,
    nutrition.calories_kcal,
    nutrition.energyKcal,
  ].find((value) => Number.isFinite(Number(value)) && Number(value) > 0) || 0);
}

function foodConfidence(food = {}) {
  return Number([
    food.confidence,
    food.weight_confidence,
    food.meta?.confidence,
  ].find((value) => Number.isFinite(Number(value)) && Number(value) > 0) || 0);
}

function visionFoodsFromReport(report = {}) {
  return report.foods || report.foodItems || report.items || [];
}

function mergeVisionFoodWithLive(food = {}) {
  const liveFoods = state.vision.latestFoods || [];
  const live = liveFoods.find((item) => item.track_id && item.track_id === food.track_id)
    || liveFoods.find((item) => displayFoodName(item) === displayFoodName(food));
  return live ? { ...live, ...food, bbox: food.bbox || live.bbox, mask_svg_path: food.mask_svg_path || live.mask_svg_path } : food;
}

function visionFoodsForCurrentReport(report = state.vision.report || {}) {
  const foods = visionFoodsFromReport(report);
  const source = foods.length ? foods : (state.vision.latestFoods || []);
  return source.map((food) => mergeVisionFoodWithLive(food));
}

function stickerShortName(name = "") {
  const text = Array.from(`${name || "食物"}`.trim());
  return text.slice(0, 5).join("") || "食物";
}

function stickerMetricValue(source = {}, key) {
  const meta = source.meta || {};
  const nutrients = source.nutrients || meta.nutrients || {};
  const aliases = {
    grams: [source.grams, source.weight_g, source.estimated_weight_g, meta.grams],
    calories: [
      source.caloriesKcal,
      source.calories_kcal,
      source.nutrition?.calories_kcal,
      nutrients.energyKcal,
      meta.caloriesKcal,
    ],
  }[key] || [];
  const value = aliases.find((item) => Number.isFinite(Number(item)) && Number(item) > 0);
  return Number(value || 0);
}

function savedStickerSvg(source = {}, extraClass = "") {
  const level = validComplianceLevel(source.complianceLevel || complianceForFood(source));
  const stroke = safeStickerColor(source.stickerColor, stickerStroke[level] || stickerStroke.generally_compliant);
  const fill = {
    compliant: "#F3F9E7",
    generally_compliant: "#FFF5CF",
    non_compliant: "#FFF0ED",
  }[level];
  const accent = {
    compliant: "#DCEEC0",
    generally_compliant: "#F7E7A6",
    non_compliant: "#F6D4CF",
  }[level];
  const label = escapeHtml(stickerShortName(displayFoodName(source)));
  const grams = stickerMetricValue(source, "grams");
  const calories = stickerMetricValue(source, "calories");
  const subText = grams ? `${Math.round(grams)}g` : (calories ? `${Math.round(calories)}kcal` : complianceMeta[level].label);
  const classes = escapeHtml(`saved-food-sticker-svg ${extraClass}`.trim());
  return `
    <svg class="${classes}" viewBox="0 0 120 120" width="120" height="120" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
      <rect x="7" y="7" width="106" height="106" rx="30" fill="#FFFDF8" stroke="#E5D9C7" stroke-width="2"></rect>
      <path d="M61 17 C82 15 101 31 104 53 C108 80 90 104 63 105 C35 106 16 88 16 62 C16 36 36 20 61 17 Z" fill="${fill}" stroke="${stroke}" stroke-width="7" stroke-linejoin="round"></path>
      <path d="M39 40 C51 27 78 31 86 48 C94 65 83 86 62 88 C42 90 29 76 31 59 C32 51 34 45 39 40 Z" fill="${accent}" opacity="0.85"></path>
      <path d="M43 58 C54 49 72 48 82 59" fill="none" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round" opacity="0.76"></path>
      <text x="60" y="67" text-anchor="middle" fill="#3F553A" font-size="18" font-weight="900">${label}</text>
      <text x="60" y="88" text-anchor="middle" fill="#786E5F" font-size="13" font-weight="900">${escapeHtml(subText)}</text>
    </svg>
  `;
}

function safeSavedStickerSvg(sticker = {}) {
  const raw = `${sticker.imageSvg || ""}`.trim();
  const isKnownSafe = (raw.includes("saved-food-sticker-svg") || raw.includes("cutout-food-sticker-svg"))
    && !/<(?:script|foreignObject)\b/i.test(raw)
    && !/\son\w+\s*=/i.test(raw)
    && !/javascript:/i.test(raw);
  return isKnownSafe ? raw : savedStickerSvg(sticker);
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
  $("bigFlower").classList.toggle("earned", Boolean(data.bigFlowerEarned));
  renderGardenFoodStickers(data.todayStickers || []);
}

function renderGardenFoodStickers(stickers = []) {
  const node = $("gardenFoodStickers");
  if (!node) return;
  if (!stickers.length) {
    node.innerHTML = `<span class="empty-vision">今日还没有保存饮食贴纸</span>`;
    return;
  }
  node.innerHTML = stickers.map((sticker) => {
    const level = validComplianceLevel(sticker.complianceLevel);
    const cls = level === "compliant" ? "compliant" : level === "non_compliant" ? "risk" : "generally";
    const itemName = displayFoodName(sticker);
    return `
      <article class="garden-food-sticker ${cls}">
        <div class="saved-sticker-art">${safeSavedStickerSvg(sticker)}</div>
        <strong>${escapeHtml(itemName)}</strong>
        <span>${complianceMeta[level]?.label || "一般符合"}</span>
      </article>
    `;
  }).join("");
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

function currentMealType() {
  const hour = new Date().getHours();
  if (hour < 10) return "breakfast";
  if (hour < 15) return "lunch";
  return "dinner";
}

function setVisionStatus(text, mode = "idle") {
  const badge = $("visionStatusBadge");
  badge.textContent = text;
  badge.dataset.mode = mode;
}

function stopVisionPolling() {
  if (state.vision.pollTimer) {
    clearInterval(state.vision.pollTimer);
    state.vision.pollTimer = null;
  }
}

function complianceForFood(food = {}) {
  const profileKey = food.profile_key || food.profileKey || food.visionMeta?.profileKey;
  const name = `${food.name || ""}`;
  const category = `${food.category || food.visionMeta?.category || ""}`;
  const cooking = `${food.cooking_method || food.visionMeta?.cookingMethod || ""}`;
  const weight = foodGrams(food);
  const calories = foodCalories(food);
  const confidence = foodConfidence(food);
  const caloriesPer100 = calories / Math.max(weight, 1) * 100;
  if (profileKey === "pork_floss_pastry" || cooking === "deep_fried" || category === "甜点" || category === "零食" || caloriesPer100 >= 320 || /高糖|甜点|蛋糕|奶茶|糖|炸|油炸|肥肉/.test(name)) {
    return "non_compliant";
  }
  if (confidence < 0.62 || caloriesPer100 >= 220 || ["pan_fried", "stir_fried", "braised"].includes(cooking)) {
    return "generally_compliant";
  }
  return "compliant";
}

function nutrientsOfFood(food = {}) {
  return food.nutrition || {
    calories_kcal: food.calories_kcal || 0,
    protein_g: food.protein_g || 0,
    carbs_g: food.carbs_g || 0,
    fat_g: food.fat_g || 0,
  };
}

function renderVisionState(sessionState = {}) {
  state.vision.sessionState = sessionState;
  state.vision.latestFoods = sessionState.foods || state.vision.latestFoods || [];
  const statusText = {
    waiting_mobile: "等待手机",
    mobile_connected: "手机已连接",
    camera_ready: "摄像头就绪",
    streaming: "采集中",
    measuring: "分析中",
    completed: "已完成",
    error: "异常",
  }[sessionState.status] || "识别中";
  setVisionStatus(statusText, sessionState.status || "idle");
  $("visionGuidance").textContent = sessionState.guidance?.message || "请用手机扫码并授权摄像头。";
  $("visionMeta").textContent = `${sessionState.frame_count || 0} 帧 / 已分析 ${sessionState.analyzed_frame_count || 0} 帧`;
  $("visionRealtimePanel").classList.remove("hidden");
  renderVisionRealtime(sessionState);
  renderVisionFoods(sessionState.foods || []);
}

function renderVisionRealtime(sessionState = {}) {
  const foods = sessionState.foods || [];
  const video = sessionState.video || {};
  const quality = sessionState.measurement_quality || {};
  const latest = $("visionLatestFrame");
  if (sessionState.latest_frame_url) {
    latest.src = `${sessionState.latest_frame_url}&v=${sessionState.frame_count || Date.now()}`;
    state.vision.latestFrameSrc = latest.src;
    $("visionEmptyFrame").style.display = "none";
  } else {
    $("visionEmptyFrame").style.display = "grid";
  }

  const total = foods.reduce((acc, food) => {
    acc.weight += foodGrams(food);
    acc.calories += foodCalories(food);
    acc.convergence += Number(food.convergence || 0);
    return acc;
  }, { weight: 0, calories: 0, convergence: 0 });
  $("visionTotalWeight").textContent = `${total.weight.toFixed(0)}g`;
  $("visionTotalCalories").textContent = `${total.calories.toFixed(0)}kcal`;
  $("visionQualityScore").textContent = `${Math.round((quality.overall || 0) * 100)}%`;
  $("visionConvergence").textContent = `${Math.round((foods.length ? total.convergence / foods.length : 0) * 100)}%`;
  $("visionQualityBars").innerHTML = qualityLabels.map(([key, label]) => {
    const value = Math.round(Number(quality[key] || 0) * 100);
    return `<div><span>${label}</span><i><b style="width:${value}%"></b></i><strong>${value}%</strong></div>`;
  }).join("");
  renderVisionOverlay(foods, video.resolution || "1280x720");
}

function renderVisionOverlay(foods = [], resolution = "1280x720") {
  const svg = $("visionOverlaySvg");
  const [width = 1280, height = 720] = resolution.split("x").map((value) => Number(value));
  state.visionFrameResolution = resolution;
  const frameSrc = $("visionLatestFrame").getAttribute("src") || "";
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const shadow = document.createElementNS("http://www.w3.org/2000/svg", "filter");
  shadow.setAttribute("id", "stickerShadow");
  shadow.setAttribute("x", "-20%");
  shadow.setAttribute("y", "-20%");
  shadow.setAttribute("width", "140%");
  shadow.setAttribute("height", "140%");
  shadow.innerHTML = `<feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#000000" flood-opacity="0.22"></feDropShadow>`;
  defs.appendChild(shadow);
  svg.appendChild(defs);
  foods.forEach((food) => {
    const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = food.bbox || [];
    const level = complianceForFood(food);
    const stroke = stickerStroke[level] || stickerStroke.generally_compliant;
    const pathD = food.mask_svg_path || `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`;
    const clipId = `foodStickerClip-${String(food.track_id || `${x1}-${y1}`).replace(/[^\w-]/g, "")}`;
    const clip = document.createElementNS("http://www.w3.org/2000/svg", "clipPath");
    clip.setAttribute("id", clipId);
    const clipPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    clipPath.setAttribute("d", pathD);
    clip.appendChild(clipPath);
    defs.appendChild(clip);

    if (frameSrc) {
      const stickerImage = document.createElementNS("http://www.w3.org/2000/svg", "image");
      stickerImage.setAttribute("href", frameSrc);
      stickerImage.setAttribute("x", "0");
      stickerImage.setAttribute("y", "0");
      stickerImage.setAttribute("width", width);
      stickerImage.setAttribute("height", height);
      stickerImage.setAttribute("preserveAspectRatio", "xMidYMid meet");
      stickerImage.setAttribute("clip-path", `url(#${clipId})`);
      stickerImage.setAttribute("filter", "url(#stickerShadow)");
      svg.appendChild(stickerImage);
    }

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pathD);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "#fffdf8");
    path.setAttribute("stroke-width", "18");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("filter", "url(#stickerShadow)");
    svg.appendChild(path);

    const colorPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    colorPath.setAttribute("d", pathD);
    colorPath.setAttribute("fill", "rgba(255,255,255,0.02)");
    colorPath.setAttribute("stroke", stroke);
    colorPath.setAttribute("stroke-width", "8");
    colorPath.setAttribute("stroke-linejoin", "round");
    colorPath.setAttribute("stroke-linecap", "round");
    colorPath.setAttribute("stroke-dasharray", level === "compliant" ? "18 13" : level === "generally_compliant" ? "28 8" : "none");
    svg.appendChild(colorPath);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", Math.max(12, x1 + 8));
    label.setAttribute("y", Math.max(30, y1 - 10));
    label.setAttribute("fill", "#fffdf8");
    label.setAttribute("paint-order", "stroke");
    label.setAttribute("stroke", "#2f302b");
    label.setAttribute("stroke-width", "5");
    label.setAttribute("font-size", "20");
    label.setAttribute("font-weight", "900");
    label.textContent = `${displayFoodName(food)} ${Math.round(food.estimated_weight_g || 0)}g`;
    svg.appendChild(label);
  });
}

function stickerThumbSvg(food = {}) {
  const frameSrc = $("visionLatestFrame")?.getAttribute("src") || "";
  const [frameWidth = 1280, frameHeight = 720] = (state.visionFrameResolution || "1280x720").split("x").map((value) => Number(value));
  const [x1 = 0, y1 = 0, x2 = 1, y2 = 1] = food.bbox || [];
  const width = Math.max(1, x2 - x1);
  const height = Math.max(1, y2 - y1);
  const hasUsableRegion = width > 12 && height > 12 && x2 > x1 && y2 > y1;
  if (!hasUsableRegion || !frameSrc) return savedStickerSvg(food, "food-sticker-thumb thumb-fallback");
  const pad = Math.max(width, height) * 0.14;
  const viewX = Math.max(0, x1 - pad);
  const viewY = Math.max(0, y1 - pad);
  const viewW = width + pad * 2;
  const viewH = height + pad * 2;
  const fallbackPath = `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`;
  const pathD = safeSvgPath(food.mask_svg_path, fallbackPath);
  const level = complianceForFood(food);
  const stroke = stickerStroke[level] || stickerStroke.generally_compliant;
  const clipId = `thumbClip-${++stickerThumbUid}-${String(food.track_id || `${x1}-${y1}`).replace(/[^\w-]/g, "")}`;
  return `
    <svg class="food-sticker-thumb" viewBox="${viewX} ${viewY} ${viewW} ${viewH}" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <clipPath id="${clipId}"><path d="${pathD}"></path></clipPath>
      </defs>
      <rect x="${viewX}" y="${viewY}" width="${viewW}" height="${viewH}" rx="${Math.max(8, pad)}" fill="#fff8ec"></rect>
      ${frameSrc ? `<image href="${frameSrc}" x="0" y="0" width="${frameWidth}" height="${frameHeight}" preserveAspectRatio="xMidYMid meet" clip-path="url(#${clipId})"></image>` : ""}
      <path d="${pathD}" fill="none" stroke="#fffdf8" stroke-width="${Math.max(14, pad * 0.34)}" stroke-linejoin="round" stroke-linecap="round"></path>
      <path d="${pathD}" fill="none" stroke="${stroke}" stroke-width="${Math.max(6, pad * 0.15)}" stroke-linejoin="round" stroke-linecap="round"></path>
    </svg>
  `;
}

async function currentVisionFrameDataUrl() {
  const img = $("visionLatestFrame");
  const src = img?.currentSrc || img?.getAttribute("src") || state.vision.latestFrameSrc || "";
  if (state.vision.latestFrameDataUrl) return state.vision.latestFrameDataUrl;
  if (!img || !src) return "";
  if (!img.complete || !img.naturalWidth || !img.naturalHeight) {
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 900);
      img.addEventListener("load", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      img.addEventListener("error", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
    });
  }
  try {
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    state.vision.latestFrameDataUrl = canvas.toDataURL("image/jpeg", 0.82);
    return state.vision.latestFrameDataUrl;
  } catch {
    try {
      const response = await fetch(src, { cache: "no-store" });
      const blob = await response.blob();
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
      state.vision.latestFrameDataUrl = `${dataUrl}`;
      return state.vision.latestFrameDataUrl;
    } catch {
      return src;
    }
  }
}

function savedCutoutStickerSvg(food = {}, imageHref = "") {
  const frameSrc = imageHref || $("visionLatestFrame")?.getAttribute("src") || "";
  const [frameWidth = 1280, frameHeight = 720] = (state.visionFrameResolution || "1280x720").split("x").map((value) => Number(value));
  const [x1 = 0, y1 = 0, x2 = 1, y2 = 1] = food.bbox || [];
  const width = Math.max(1, x2 - x1);
  const height = Math.max(1, y2 - y1);
  const hasUsableRegion = width > 12 && height > 12 && x2 > x1 && y2 > y1 && frameSrc;
  if (!hasUsableRegion) return savedStickerSvg(food);
  const pad = Math.max(width, height) * 0.18;
  const viewX = Math.max(0, x1 - pad);
  const viewY = Math.max(0, y1 - pad);
  const viewW = width + pad * 2;
  const viewH = height + pad * 2;
  const fallbackPath = `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`;
  const pathD = safeSvgPath(food.mask_svg_path, fallbackPath);
  const level = complianceForFood(food);
  const stroke = stickerStroke[level] || stickerStroke.generally_compliant;
  const clipId = `savedCutout-${++stickerThumbUid}-${String(food.track_id || `${x1}-${y1}`).replace(/[^\w-]/g, "")}`;
  return `
    <svg class="saved-food-sticker-svg cutout-food-sticker-svg" viewBox="0 0 120 120" width="120" height="120" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
      <rect x="6" y="6" width="108" height="108" rx="30" fill="#fffdf8" stroke="#e5d9c7" stroke-width="2"></rect>
      <svg x="10" y="10" width="100" height="100" viewBox="${viewX} ${viewY} ${viewW} ${viewH}" preserveAspectRatio="xMidYMid meet">
        <defs>
          <clipPath id="${clipId}"><path d="${pathD}"></path></clipPath>
        </defs>
        <rect x="${viewX}" y="${viewY}" width="${viewW}" height="${viewH}" rx="${Math.max(8, pad)}" fill="#fff8ec"></rect>
        <image href="${escapeHtml(frameSrc)}" x="0" y="0" width="${frameWidth}" height="${frameHeight}" preserveAspectRatio="none" clip-path="url(#${clipId})"></image>
        <path d="${pathD}" fill="none" stroke="#fffdf8" stroke-width="${Math.max(14, pad * 0.34)}" stroke-linejoin="round" stroke-linecap="round"></path>
        <path d="${pathD}" fill="none" stroke="${stroke}" stroke-width="${Math.max(6, pad * 0.15)}" stroke-linejoin="round" stroke-linecap="round"></path>
      </svg>
    </svg>
  `;
}

async function stickerSavePayload(food = {}, frameDataUrl = "") {
  const level = complianceForFood(food);
  const grams = foodGrams(food);
  const caloriesKcal = foodCalories(food);
  const confidence = foodConfidence(food);
  return {
    itemName: displayFoodName(food),
    complianceLevel: level,
    stickerColor: stickerStroke[level] || stickerStroke.generally_compliant,
    sourceSessionId: state.vision.report?.session_id || state.vision.session?.session_id,
    sourceTrackId: food.track_id,
    imageSvg: savedCutoutStickerSvg({ ...food, complianceLevel: level, stickerColor: stickerStroke[level] || stickerStroke.generally_compliant }, frameDataUrl),
    meta: {
      grams,
      caloriesKcal,
      confidence,
      profileKey: food.profile_key || food.profileKey,
      category: food.category,
      cookingMethod: food.cooking_method,
      cookingMethodName: food.cooking_method_name,
    },
  };
}

function renderVisionFoods(foods = []) {
  const node = $("visionFoodList");
  if (!foods.length) {
    node.innerHTML = `<div class="empty-vision">等待识别食物主体。</div>`;
    return;
  }
  node.innerHTML = foods.map((food) => {
    const level = complianceForFood(food);
    const meta = complianceMeta[level];
    return `
    <article class="vision-food ${meta.className}">
      ${stickerThumbSvg(food)}
      <div>
        <strong>${displayFoodName(food)}</strong>
        <span>${food.cooking_method_name || "估算"} · ${meta.label} · 置信度 ${Math.round(foodConfidence(food) * 100)}%</span>
      </div>
      <b>${Math.round(foodGrams(food))}g</b>
    </article>
  `;
  }).join("");
}

function renderVisionReport(report = {}) {
  const summary = report.meal_summary || {};
  const foods = visionFoodsForCurrentReport(report);
  const totalWeight = Number(summary.total_weight_g || 0) || foods.reduce((sum, food) => sum + foodGrams(food), 0);
  const totalCalories = Number(summary.total_calories_kcal || 0) || foods.reduce((sum, food) => sum + foodCalories(food), 0);
  $("visionReportSummary").classList.remove("hidden");
  $("visionReportSummary").innerHTML = `
    <div class="vision-total">
      <span>本次识别</span>
      <strong>${Math.round(totalWeight)}g</strong>
      <span>${Math.round(totalCalories)} kcal</span>
    </div>
    <div class="vision-report-foods">
      ${foods.map((food) => {
        const level = complianceForFood(food);
        const meta = complianceMeta[level];
        return `
          <article class="report-food-card ${meta.className}">
            ${stickerThumbSvg(food)}
            <div>
              <strong>${displayFoodName(food)}</strong>
              <span>${food.cooking_method_name || "估算"} · ${meta.label}</span>
            </div>
            <b>${Math.round(foodGrams(food))}g</b>
            <small>${Math.round(foodCalories(food))} kcal · 置信度 ${Math.round(foodConfidence(food) * 100)}%</small>
          </article>
        `;
      }).join("") || "<span>暂无可同步食物</span>"}
    </div>
  `;
  const redFoods = foods.filter((food) => complianceForFood(food) === "non_compliant");
  if (redFoods.length) showRisk(redFoods);
}

function renderStickersFromIntakes(records = []) {
  const items = records.flatMap((record) => record.items || []).slice(0, 8);
  if (!items.length) return;
  $("infoScreen").querySelector(".sticker-strip").innerHTML = items.map((item) => {
    const level = item.complianceLevel || "generally_compliant";
    const cls = level === "compliant" ? "compliant" : level === "non_compliant" ? "risk" : "generally";
    return `<div class="sticker ${cls}">${displayFoodName(item)}<small>${Math.round(item.grams || 0)}g</small></div>`;
  }).join("");
}

async function refreshIntakeStickers() {
  if (!state.user) return;
  const data = await api(`/api/mmy/intake-records?userId=${encodeURIComponent(userId())}`);
  renderStickersFromIntakes(data.records || []);
}

async function createVisionSession() {
  if (!state.user) {
    alert("请先登录并生成营养方案。");
    return;
  }
  stopVisionPolling();
  state.vision.report = null;
  state.vision.syncedRecord = null;
  state.vision.latestFoods = [];
  state.vision.latestFrameSrc = "";
  state.vision.latestFrameDataUrl = "";
  $("visionReportSummary").classList.add("hidden");
  $("syncVisionBtn").disabled = true;
  const session = await api("/api/sessions", { method: "POST", body: JSON.stringify({}) });
  state.vision.session = session;
  $("visionSessionPanel").classList.remove("hidden");
  $("visionQr").src = session.qr_code_url;
  $("captureLink").href = `/capture?session_id=${encodeURIComponent(session.session_id)}&token=${encodeURIComponent(session.token)}`;
  $("finishVisionBtn").disabled = false;
  setVisionStatus("等待手机", "waiting_mobile");
  renderVisionFoods([]);
  state.vision.pollTimer = setInterval(refreshVisionSessionState, 1400);
  await refreshVisionSessionState();
}

async function refreshVisionSessionState() {
  const sessionId = state.vision.session?.session_id;
  if (!sessionId) return;
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/state`);
    renderVisionState(data);
    if (data.status === "completed" || data.status === "error") stopVisionPolling();
  } catch (error) {
    setVisionStatus("连接异常", "error");
    $("visionGuidance").textContent = error.message;
  }
}

async function finishVisionSession() {
  const sessionId = state.vision.session?.session_id;
  if (!sessionId) return;
  const report = await api(`/api/sessions/${encodeURIComponent(sessionId)}/finish`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  state.vision.report = report;
  stopVisionPolling();
  setVisionStatus("报告已生成", "completed");
  renderVisionReport(report);
  $("syncVisionBtn").disabled = !visionFoodsForCurrentReport(report).length;
}

async function syncVisionIntake() {
  if (!state.user || !state.vision.report) return;
  const frameDataUrl = await currentVisionFrameDataUrl();
  const foods = visionFoodsForCurrentReport(state.vision.report);
  const stickers = await Promise.all(foods.map((food) => stickerSavePayload(food, frameDataUrl)));
  const reportForSync = {
    ...state.vision.report,
    foods: visionFoodsFromReport(state.vision.report).length ? visionFoodsFromReport(state.vision.report) : foods,
  };
  const data = await api("/api/mmy/vision/intake-sync", {
    method: "POST",
    body: JSON.stringify({
      userId: userId(),
      mealType: currentMealType(),
      reportId: state.vision.report.report_id,
      report: reportForSync,
      stickers,
    }),
  });
  state.vision.syncedRecord = data.record;
  $("syncVisionBtn").disabled = true;
  setVisionStatus("已同步", "completed");
  renderStickersFromIntakes([data.record]);
  await refreshGarden();
  await refreshReport();
  if (data.adjustment?.riskLevel === "red") showRisk(data.record.items || []);
}

function riskKeyFromItems(items = []) {
  return items.map((item) => `${displayFoodName(item)}:${Math.round(item.grams || item.weight_g || item.estimated_weight_g || 0)}`).join("|");
}

function showRisk(items = []) {
  $("riskAlert").classList.remove("hidden");
  const redItems = (items || []).filter((item) => {
    if (item.complianceLevel) return item.complianceLevel === "non_compliant";
    return complianceForFood(item) === "non_compliant";
  });
  state.vision.lastRiskItems = redItems;
  const riskKey = riskKeyFromItems(redItems);
  $("riskReason").textContent = redItems.length
    ? "识别到非常不符合当前营养方案的红色风险食物，建议替换后再继续。"
    : "当前食物与营养方案不匹配，建议替换为低糖、高纤维选择。";
  $("riskItems").innerHTML = redItems.map((item) => `
    <div class="risk-item">
      <strong>${displayFoodName(item)}</strong>
      <span>${Math.round(item.grams || item.weight_g || 0)}g</span>
    </div>
  `).join("");
  if (riskKey && riskKey !== state.vision.lastRiskNotifyKey) {
    state.vision.lastRiskNotifyKey = riskKey;
    speakRiskAlert(redItems);
    notifyEmergencyContact(redItems, { auto: true }).catch((error) => {
      $("smsFeedback").textContent = error.message;
    });
  }
}

async function openSmsFlow() {
  await notifyEmergencyContact(state.vision.lastRiskItems || [], { auto: false });
}

function closeRisk() {
  $("riskAlert").classList.add("hidden");
}

function speakRiskAlert(items = []) {
  const names = items.map(displayFoodName).filter(Boolean).join("、") || "当前食物";
  const text = `慢慢养提醒，识别到红色风险食物：${names}。建议先暂停进食，并联系家人确认。`;
  if (!("speechSynthesis" in window)) return false;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 0.92;
  utterance.volume = 1;
  window.speechSynthesis.speak(utterance);
  return true;
}

async function notifyEmergencyContact(items = [], { auto = false } = {}) {
  if (!state.profile?.emergencyContactPhone) {
    $("smsFeedback").textContent = "请先填写紧急联系人手机号。";
    return false;
  }
  const names = items.map(displayFoodName).filter(Boolean).join("、") || "红色风险食物";
  const data = await api("/api/mmy/sms/confirm", {
    method: "POST",
    body: JSON.stringify({
      contact: { phone: state.profile.emergencyContactPhone },
      message: `慢慢养提醒：识别到${names}，属于红色风险食物，请及时关注 ${state.user?.phone || "用户"} 的饮食情况。`,
    }),
  });
  $("smsFeedback").textContent = data.feedback || "已准备拉起系统短信。";
  if (auto || window.confirm("将拉起系统短信界面，由用户手动确认发送。是否继续？")) {
    window.location.href = data.smsUrl;
  }
  return true;
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
  if (data.plan) {
    state.plan = data.plan;
    persistSession();
    renderPlan();
    const div = document.createElement("div");
    div.className = "message agent";
    div.textContent = "已根据反馈调整记录页中的三餐食谱。";
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
  if (target === "recordScreen") refreshLatestPlan();
}

function bindEvents() {
  $("sendCodeBtn").addEventListener("click", sendCode);
  $("loginBtn").addEventListener("click", smsLogin);
  $("oneTapBtn").addEventListener("click", oneTapLogin);
  $("logoutBtn").addEventListener("click", logout);
  $("saveProfileBtn").addEventListener("click", saveProfileAndGenerate);
  $("diseaseType").addEventListener("change", toggleDiseaseOther);
  $("createVisionBtn").addEventListener("click", createVisionSession);
  $("finishVisionBtn").addEventListener("click", finishVisionSession);
  $("syncVisionBtn").addEventListener("click", syncVisionIntake);
  $("visionContractBtn").addEventListener("click", loadVisionContract);
  $("riskCloseBtn").addEventListener("click", closeRisk);
  $("riskContinueBtn").addEventListener("click", closeRisk);
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
  updateLoginState();
  toggleDiseaseOther();
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
  restoreSession();
}

init();
