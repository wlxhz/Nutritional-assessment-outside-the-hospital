const qs = (selector) => document.querySelector(selector);
const params = new URLSearchParams(location.search);

const capture = {
  sessionId: params.get("session_id"),
  token: params.get("token"),
  stream: null,
  timer: null,
  uploading: false,
  frameIntervalMs: 700,
};

qs("#mobileSessionId").value = capture.sessionId || "missing";
qs("#joinBtn").addEventListener("click", joinSession);
qs("#cameraBtn").addEventListener("click", requestCamera);
qs("#streamBtn").addEventListener("click", toggleStream);

function setStatus(status, label) {
  const pill = qs("#mobileStatus");
  pill.textContent = label;
  pill.className = `pill ${status}`;
}

function setHint(message) {
  qs("#mobileHint").value = message;
}

async function joinSession() {
  if (!capture.sessionId || !capture.token) {
    setStatus("error", "参数缺失");
    setHint("采集地址缺少 session_id 或 token，请重新扫码。");
    return;
  }
  const payload = {
    token: capture.token,
    device: {
      platform: "android",
      model: navigator.userAgent,
      user_agent: navigator.userAgent,
      app_version: "mobile-web-demo",
    },
  };
  const response = await fetch(`/api/sessions/${capture.sessionId}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    setStatus("error", "连接失败");
    setHint(await response.text());
    return;
  }
  setStatus("ready", "已连接");
  setHint("会话已连接。请点击“授权摄像头”，Android 浏览器会弹出权限确认。");
  qs("#cameraBtn").disabled = false;
  qs("#joinBtn").disabled = true;
}

async function requestCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
      },
    });
    capture.stream = stream;
    qs("#cameraPreview").srcObject = stream;
    qs("#cameraEmpty").style.display = "none";
    qs("#streamBtn").disabled = false;
    setStatus("ready", "摄像头就绪");
    setHint("摄像头已授权。请将餐盘放入框内，然后开始推流。");
    await sendEvent("camera_permission_granted", { tracks: stream.getVideoTracks().map((track) => track.label) });
  } catch (error) {
    setStatus("error", "授权失败");
    setHint(`摄像头授权失败：${error.message}。Android 真机访问电脑 IP 时通常需要 HTTPS 地址。`);
    await sendEvent("camera_permission_denied", { message: error.message });
  }
}

async function toggleStream() {
  if (capture.timer) {
    clearInterval(capture.timer);
    capture.timer = null;
    qs("#streamBtn").textContent = "开始推流";
    setStatus("ready", "已暂停");
    setHint("推流已暂停，可以重新开始。");
    await sendEvent("stream_stopped");
    return;
  }
  if (!capture.stream) {
    setHint("请先授权摄像头。");
    return;
  }
  await sendEvent("stream_started");
  qs("#streamBtn").textContent = "停止推流";
  setStatus("streaming", "推流中");
  setHint("正在上传视频帧。请缓慢绕餐盘移动，补充侧面角度。");
  capture.timer = setInterval(uploadFrame, capture.frameIntervalMs);
  uploadFrame();
}

async function uploadFrame() {
  if (capture.uploading || !capture.stream) return;
  const video = qs("#cameraPreview");
  if (!video.videoWidth || !video.videoHeight) return;
  capture.uploading = true;
  try {
    const canvas = qs("#captureCanvas");
    const targetWidth = Math.min(960, video.videoWidth);
    const targetHeight = Math.round(targetWidth * video.videoHeight / video.videoWidth);
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, targetWidth, targetHeight);
    const image = canvas.toDataURL("image/jpeg", 0.72);
    const payload = {
      token: capture.token,
      image,
      width: targetWidth,
      height: targetHeight,
      timestamp_ms: Date.now(),
      device_motion: {},
    };
    const response = await fetch(`/api/sessions/${capture.sessionId}/frames`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await response.text());
    const state = await response.json();
    setHint(state.guidance.message);
  } catch (error) {
    setStatus("error", "上传失败");
    setHint(`上传失败：${error.message}`);
  } finally {
    capture.uploading = false;
  }
}

async function sendEvent(event, payload = {}) {
  if (!capture.sessionId || !capture.token) return;
  await fetch(`/api/sessions/${capture.sessionId}/capture-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: capture.token, event, payload }),
  });
}

if (!window.isSecureContext) {
  setStatus("error", "非安全上下文");
  setHint("当前页面不是安全上下文。Android 真机摄像头授权通常需要 HTTPS；请使用 README 中的 HTTPS 启动方式或内网穿透 HTTPS 地址。");
} else {
  setStatus("waiting", "待连接");
  setHint("请点击“连接会话”。");
}
