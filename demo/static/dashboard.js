const qs = (selector) => document.querySelector(selector);

const state = {
  session: null,
  socket: null,
  latest: null,
  report: null,
};

const qualityLabels = [
  ["angle_coverage", "视角覆盖"],
  ["depth_completeness", "深度完整度"],
  ["mask_stability", "分割稳定性"],
  ["motion_quality", "运动质量"],
  ["lighting", "光照质量"],
  ["blur", "清晰度"],
  ["plate_visibility", "餐盘可见"],
];

qs("#createSessionBtn").addEventListener("click", createSession);
qs("#finishBtn").addEventListener("click", finishSession);
qs("#copyUrlBtn").addEventListener("click", copyCaptureUrl);
qs("#openCaptureBtn").addEventListener("click", () => {
  if (state.session?.capture_url) window.open(state.session.capture_url, "_blank", "noopener");
});

async function createSession() {
  const response = await fetch("/api/sessions", { method: "POST" });
  if (!response.ok) throw new Error("create session failed");
  state.session = await response.json();
  state.report = null;
  qs("#reportJson").textContent = "";
  qs("#reportState").textContent = "未生成";
  qs("#sessionId").value = state.session.session_id;
  qs("#captureUrl").value = state.session.capture_url;
  qs("#qrImage").src = `${state.session.qr_code_url}?t=${Date.now()}`;
  qs("#copyUrlBtn").disabled = false;
  qs("#openCaptureBtn").disabled = false;
  qs("#finishBtn").disabled = false;
  connectEvents();
  const snapshot = await fetchJson(`/api/sessions/${state.session.session_id}/state`);
  render(snapshot);
}

function connectEvents() {
  if (state.socket) state.socket.close();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocol}://${location.host}/ws/sessions/${state.session.session_id}/events`;
  state.socket = new WebSocket(url);
  state.socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.state) render(message.state);
    if (message.report) renderReport(message.report);
  };
  state.socket.onclose = () => updateStatus("error", "连接断开");
}

async function finishSession() {
  if (!state.session) return;
  const report = await fetchJson(`/api/sessions/${state.session.session_id}/finish`, { method: "POST" });
  renderReport(report);
}

async function copyCaptureUrl() {
  if (!state.session?.capture_url) return;
  await navigator.clipboard.writeText(state.session.capture_url);
  qs("#copyUrlBtn").textContent = "已复制";
  setTimeout(() => {
    qs("#copyUrlBtn").textContent = "复制采集地址";
  }, 1200);
}

function render(nextState) {
  state.latest = nextState;
  updateStatus(nextState.status, statusLabel(nextState.status));
  qs("#videoMeta").textContent = `${nextState.video.resolution} · ${nextState.video.fps} FPS · ${nextState.elapsed_seconds}s`;
  qs("#analyzerLabel").textContent = `Analyzer: ${nextState.analyzer} / ${nextState.model_name}`;
  qs("#guidanceBadge").textContent = nextState.guidance.message;
  qs("#frameCount").textContent = `${nextState.frame_count} frames`;

  if (nextState.latest_frame_url) {
    qs("#latestFrame").src = `${nextState.latest_frame_url}&v=${nextState.frame_count}`;
    qs("#emptyVideo").style.display = "none";
    if (!nextState.foods.length && nextState.frame_count > 0) {
      qs("#guidanceBadge").textContent = "已收到手机画面，正在分析当前帧。";
    }
  }

  renderOverlay(nextState);
  renderFoods(nextState.foods);
  renderSummary(nextState.foods);
  renderQuality(nextState.measurement_quality);
}

function renderOverlay(nextState) {
  const svg = qs("#overlaySvg");
  const resolution = nextState.video.resolution.split("x").map((value) => Number(value));
  const width = resolution[0] || 1280;
  const height = resolution[1] || 720;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";
  nextState.foods.forEach((food) => {
    const [x1, y1, x2, y2] = food.bbox;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", food.mask_svg_path || `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`);
    path.setAttribute("fill", food.color);
    path.setAttribute("fill-opacity", "0.22");
    path.setAttribute("stroke", food.color);
    path.setAttribute("stroke-width", "4");
    svg.appendChild(path);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", x1);
    rect.setAttribute("y", y1);
    rect.setAttribute("width", x2 - x1);
    rect.setAttribute("height", y2 - y1);
    rect.setAttribute("fill", "none");
    rect.setAttribute("stroke", food.color);
    rect.setAttribute("stroke-width", "3");
    svg.appendChild(rect);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", x1);
    label.setAttribute("y", Math.max(24, y1 - 8));
    label.setAttribute("fill", food.color);
    label.setAttribute("font-size", "22");
    label.setAttribute("font-weight", "800");
    label.textContent = `${food.name} ${Math.round(food.estimated_weight_g)}g ${Math.round(food.weight_confidence * 100)}%`;
    svg.appendChild(label);
  });
}

function renderFoods(foods) {
  qs("#foodRows").innerHTML = foods.map((food) => `
    <tr>
      <td>${food.name}<small>${food.category}</small></td>
      <td>${food.track_id}</td>
      <td>${food.estimated_weight_g}g</td>
      <td>±${food.weight_error_g}g</td>
      <td>${food.volume_ml}ml</td>
      <td>${food.nutrition.calories_kcal}kcal</td>
      <td>${food.nutrition.protein_g}g</td>
      <td>${food.nutrition.carbs_g}g</td>
      <td>${food.nutrition.fat_g}g</td>
      <td>${Math.round(food.weight_confidence * 100)}%</td>
    </tr>
  `).join("");
}

function renderSummary(foods) {
  const total = foods.reduce((acc, food) => {
    acc.weight += food.estimated_weight_g;
    acc.calories += food.nutrition.calories_kcal;
    acc.protein += food.nutrition.protein_g;
    acc.carbs += food.nutrition.carbs_g;
    acc.fat += food.nutrition.fat_g;
    acc.confidence += food.weight_confidence;
    return acc;
  }, { weight: 0, calories: 0, protein: 0, carbs: 0, fat: 0, confidence: 0 });
  qs("#totalWeight").textContent = `${total.weight.toFixed(1)}g`;
  qs("#totalCalories").textContent = `${total.calories.toFixed(1)}kcal`;
  qs("#totalProtein").textContent = `${total.protein.toFixed(1)}g`;
  qs("#totalCarbs").textContent = `${total.carbs.toFixed(1)}g`;
  qs("#totalFat").textContent = `${total.fat.toFixed(1)}g`;
  qs("#overallConfidence").textContent = `${Math.round((foods.length ? total.confidence / foods.length : 0) * 100)}%`;
}

function renderQuality(quality) {
  qs("#qualityScore").textContent = `${Math.round(quality.overall * 100)}%`;
  qs("#qualityBars").innerHTML = qualityLabels.map(([key, label]) => {
    const value = quality[key] || 0;
    return `<div><span>${label}</span><i><b style="width:${Math.round(value * 100)}%"></b></i><strong>${Math.round(value * 100)}%</strong></div>`;
  }).join("");
}

function renderReport(report) {
  state.report = report;
  qs("#reportState").textContent = "已生成";
  qs("#reportJson").textContent = JSON.stringify(report, null, 2);
}

function updateStatus(status, label) {
  const pill = qs("#statusPill");
  pill.textContent = label;
  pill.className = `pill ${status}`;
}

function statusLabel(status) {
  return {
    waiting_mobile: "等待手机",
    mobile_connected: "手机已连接",
    camera_ready: "摄像头就绪",
    streaming: "推流中",
    measuring: "测量中",
    completed: "已完成",
    error: "错误",
  }[status] || status;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

createSession().catch((error) => {
  updateStatus("error", "创建失败");
  qs("#guidanceBadge").textContent = error.message;
});
