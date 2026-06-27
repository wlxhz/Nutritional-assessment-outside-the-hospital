# 视觉识别板块 API 接口文档

版本：v0.1
日期：2026-06-27
当前服务：FastAPI，默认本地端口 `8000`，手机 HTTPS 测试端口 `8443`

## 1. 接口总览

基础地址按环境配置：

```text
本地 Dashboard: http://127.0.0.1:8000
本地手机采集: https://{电脑局域网IP}:8443
生产环境示例: https://vision-api.example.com
```

当前接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/api/network-info` | 获取 Dashboard 和手机采集基础地址 |
| GET | `/api/foods` | 查看内置食材数据库 |
| POST | `/api/sessions` | 创建识别会话 |
| GET | `/api/sessions/{session_id}/state` | 获取当前会话状态 |
| GET | `/api/sessions/{session_id}/qrcode` | 获取手机采集二维码 PNG |
| POST | `/api/sessions/{session_id}/join` | 手机/App 加入会话 |
| POST | `/api/sessions/{session_id}/capture-event` | 上报采集端事件 |
| POST | `/api/sessions/{session_id}/frames` | 上传 JPEG 视频帧 |
| GET | `/api/sessions/{session_id}/latest-frame` | 获取最近一帧 JPEG |
| POST | `/api/sessions/{session_id}/finish` | 结束采集并生成报告 |
| GET | `/api/reports/{report_id}` | 获取最终报告 |
| WS | `/ws/sessions/{session_id}/events` | 订阅会话实时状态 |

通用约定：

- 请求体均为 JSON，除 `qrcode` 和 `latest-frame`。
- `token` 当前放在请求 body 中。
- 时间字段为 ISO 8601 字符串。
- 克重单位为 `g`。
- 热量单位为 `kcal`。
- bbox 坐标为上传图像坐标系，格式 `[x1, y1, x2, y2]`。

## 2. 状态枚举

### 2.1 SessionStatus

| 值 | 说明 |
| --- | --- |
| `waiting_mobile` | 等待手机或 App 加入 |
| `mobile_connected` | 采集端已加入 |
| `camera_ready` | 摄像头已授权 |
| `streaming` | 采集端开始推流 |
| `measuring` | 后端正在接收并分析帧 |
| `completed` | 采集完成 |
| `error` | 出错 |

### 2.2 CaptureEvent

| 值 | 说明 |
| --- | --- |
| `camera_permission_granted` | 摄像头授权成功 |
| `camera_permission_denied` | 摄像头授权失败 |
| `stream_started` | 开始推流 |
| `stream_stopped` | 停止推流 |
| `capture_error` | 采集端发生错误 |

### 2.3 Guidance needed_action

常见值：

| 值 | 建议 App 行为 |
| --- | --- |
| `connect_mobile` | 提示连接手机/采集端 |
| `grant_camera` | 提示授权摄像头 |
| `start_stream` | 提示开始推流 |
| `scan_plate` | 提示将餐盘放入画面并缓慢移动 |
| `continue_scan` | 继续采集 |
| `improve_lighting` | 改善光照 |
| `move_closer` | 靠近一些 |
| `change_angle` | 改变角度 |
| `hold_still` | 保持稳定 |
| `check_mobile` | 检查采集端错误 |

### 2.4 scale_status

| 值 | 说明 | App 展示建议 |
| --- | --- | --- |
| `calibrating` | 正在积累尺度基准 | 校准中 |
| `stable` | 已形成稳定尺度基准 | 已稳定 |
| `too_close` | 镜头过近，已用历史尺度校正 | 近距校正 |
| `too_far` | 主体过小，已用历史尺度校正 | 远距校正 |
| `corrected` | 检测到尺度变化，已校正 | 尺度校正 |
| `needs_reference` | 暂无可靠标准帧 | 请保持主体完整入镜 |

## 3. 数据结构

### 3.1 DeviceInfo

```json
{
  "platform": "android",
  "model": "Pixel 8",
  "user_agent": "Mozilla/5.0 ...",
  "app_version": "1.0.0"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `platform` | string | 否 | `android` / `ios` / `web` |
| `model` | string | 否 | 机型或 UA |
| `user_agent` | string | 否 | WebView/浏览器 UA |
| `app_version` | string | 否 | App 或采集端版本 |

### 3.2 FrameUpload

```json
{
  "token": "once_xxx",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...",
  "width": 640,
  "height": 1138,
  "timestamp_ms": 1782570000000,
  "device_motion": {
    "rotation_rate": {},
    "acceleration": {},
    "focal_length": null
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `token` | string | 是 | 创建 session 时返回的一次性 token |
| `image` | string | 是 | JPEG data URL 或纯 base64 JPEG |
| `width` | number | 是 | 上传图像宽度 |
| `height` | number | 是 | 上传图像高度 |
| `timestamp_ms` | number | 是 | 客户端采集时间戳 |
| `device_motion` | object | 否 | 设备姿态、焦距、相机参数，当前可为空 |

### 3.3 Nutrition

```json
{
  "calories_kcal": 367.7,
  "protein_g": 40.0,
  "carbs_g": 9.0,
  "fat_g": 17.5,
  "fiber_g": 0.0,
  "sodium_mg": 327.0
}
```

### 3.4 FoodTrack

```json
{
  "track_id": "food_1",
  "name": "炸制鸡胸肉",
  "category": "蛋白质",
  "profile_key": "chicken",
  "cooking_method": "deep_fried",
  "cooking_method_name": "炸制",
  "cooking_confidence": 0.72,
  "raw_weight_g": 226.4,
  "estimated_weight_g": 129.1,
  "weight_error_g": 12.0,
  "weight_confidence": 0.74,
  "area_ratio": 0.2258,
  "bbox_area_ratio": 0.2654,
  "scale_view_quality": 0.96,
  "scale_corrected": true,
  "scale_confidence": 0.65,
  "scale_sample_count": 6,
  "scale_status": "too_close",
  "state": "tracking",
  "bbox": [211, 172, 590, 682],
  "polygon": [[211,172],[590,172],[590,682],[211,682]],
  "mask_svg_path": "M 211 172 L 590 172 L 590 682 L 211 682 Z",
  "color": "#7cf4bd",
  "confidence": 0.81,
  "volume_ml": 126.6,
  "volume_confidence": 0.82,
  "density_g_per_ml": 1.02,
  "visible_frames": 10,
  "sample_count": 10,
  "stable_seconds": 5.4,
  "convergence": 0.52,
  "first_seen_seconds": 0.6,
  "last_seen_seconds": 6.0,
  "nutrition": {}
}
```

关键字段说明：

| 字段 | 说明 |
| --- | --- |
| `track_id` | 同一食物主体的稳定 ID |
| `name` | 用于展示的食物名称，可能包含烹饪方式前缀 |
| `profile_key` | 营养数据库中的食物 key |
| `cooking_method` | 烹饪方式 key |
| `raw_weight_g` | 当前帧原始估重，受距离影响较大 |
| `estimated_weight_g` | 推荐展示的最终估重，已做时序与尺度校正 |
| `weight_error_g` | 估重误差 |
| `weight_confidence` | 克重置信度，0-1 |
| `area_ratio` | mask 占整帧比例 |
| `bbox_area_ratio` | bbox 占整帧比例 |
| `scale_corrected` | 当前是否使用历史尺度校正 |
| `scale_status` | 尺度状态 |
| `sample_count` | 当前主体累计样本数 |
| `convergence` | 收敛度，0-1 |
| `nutrition` | 按估重和烹饪方式计算的营养 |

App 主展示应使用 `estimated_weight_g`，不要使用 `raw_weight_g` 作为最终克重。

### 3.5 MeasurementQuality

```json
{
  "angle_coverage": 0.52,
  "depth_completeness": 0.48,
  "mask_stability": 0.74,
  "motion_quality": 0.68,
  "lighting": 0.86,
  "blur": 0.72,
  "plate_visibility": 0.65,
  "overall": 0.66
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `angle_coverage` | 视角覆盖程度 |
| `depth_completeness` | 深度/体积信息完整度 |
| `mask_stability` | 主体分割稳定度 |
| `motion_quality` | 连续采集质量 |
| `lighting` | 光照质量 |
| `blur` | 清晰度 |
| `plate_visibility` | 主体可见程度 |
| `overall` | 综合质量 |

### 3.6 SessionState

```json
{
  "session_id": "sess_20260627_212428_18c2",
  "status": "measuring",
  "created_at": "2026-06-27T21:24:28.847688+08:00",
  "expires_at": "2026-06-27T21:54:28.847688+08:00",
  "elapsed_seconds": 18.4,
  "frame_count": 35,
  "analyzed_frame_count": 32,
  "analyzer": "opencv-fallback",
  "model_name": "opencv-fallback",
  "capture_url": "https://172.16.252.111:8443/capture?session_id=...&token=...",
  "qr_code_url": "/api/sessions/sess_xxx/qrcode",
  "video": {
    "fps": 1.9,
    "resolution": "640x1138",
    "quality": "good",
    "last_frame_at": "2026-06-27T21:24:44+08:00"
  },
  "measurement_quality": {},
  "foods": [],
  "guidance": {
    "message": "检测到镜头距离过近，当前克重已使用历史尺度基准校正；请稍微后退并保持主体完整入镜。",
    "needed_action": "continue_scan"
  },
  "latest_frame_url": "/api/sessions/sess_xxx/latest-frame?t=35",
  "device": {}
}
```

## 4. 接口详情

### 4.1 健康检查

```http
GET /health
```

响应：

```json
{
  "ok": "true",
  "analyzer": "opencv-fallback",
  "model": "opencv-fallback"
}
```

说明：

- `analyzer=yolo11-seg` 表示已加载 YOLOv11 分割模型。
- `analyzer=opencv-fallback` 表示当前使用 OpenCV fallback。

### 4.2 获取网络信息

```http
GET /api/network-info
```

响应：

```json
{
  "dashboard_base_url": "http://127.0.0.1:8000",
  "mobile_base_url": "https://172.16.252.111:8443",
  "lan_ip": "172.16.252.111"
}
```

用途：

- App 或测试工具可读取当前手机采集地址。
- 本地测试时用于确认手机和电脑是否在同一局域网。

### 4.3 获取食材数据库

```http
GET /api/foods
```

响应：

```json
{
  "count": 64,
  "foods": [
    {
      "key": "rice",
      "display_name": "米饭",
      "category": "主食",
      "density_g_per_ml": 0.72,
      "density_std_g_per_ml": 0.08,
      "calories_kcal_per_100g": 116,
      "protein_g_per_100g": 2.6,
      "carbs_g_per_100g": 25.9,
      "fat_g_per_100g": 0.3
    }
  ]
}
```

### 4.4 创建会话

```http
POST /api/sessions
```

请求体：无。

响应：

```json
{
  "session_id": "sess_20260627_212428_18c2",
  "token": "once_A55u2W2e7pKu8RWz",
  "capture_url": "https://172.16.252.111:8443/capture?session_id=sess_20260627_212428_18c2&token=once_A55u2W2e7pKu8RWz",
  "qr_code_url": "/api/sessions/sess_20260627_212428_18c2/qrcode",
  "events_url": "/ws/sessions/sess_20260627_212428_18c2/events",
  "expires_at": "2026-06-27T21:54:28.847688+08:00"
}
```

App 接入说明：

- 原生 App 接入时，可忽略 `capture_url`，直接使用 `session_id` 和 `token` 调后续接口。
- WebView 快速接入时，直接打开 `capture_url`。
- Dashboard 使用 `qr_code_url` 显示二维码。

### 4.5 获取会话状态

```http
GET /api/sessions/{session_id}/state
```

响应：`SessionState`。

使用场景：

- App 首次进入识别页拉取状态。
- WebSocket 断开后用轮询兜底。
- 调试当前识别结果。

### 4.6 获取二维码

```http
GET /api/sessions/{session_id}/qrcode
```

响应：

- `image/png`
- 内容是 `capture_url` 的二维码。

适用于 PC Dashboard 引导手机扫码。

### 4.7 加入会话

```http
POST /api/sessions/{session_id}/join
Content-Type: application/json
```

请求：

```json
{
  "token": "once_A55u2W2e7pKu8RWz",
  "device": {
    "platform": "android",
    "model": "Pixel 8",
    "user_agent": "Mozilla/5.0 ...",
    "app_version": "1.0.0"
  }
}
```

响应：

```json
{
  "ok": true,
  "session_status": "mobile_connected",
  "state": {}
}
```

错误：

| 状态码 | 说明 |
| --- | --- |
| 403 | token 无效 |
| 404 | session 不存在 |
| 422 | 请求体格式错误 |

### 4.8 上报采集事件

```http
POST /api/sessions/{session_id}/capture-event
Content-Type: application/json
```

请求：

```json
{
  "token": "once_A55u2W2e7pKu8RWz",
  "event": "camera_permission_granted",
  "payload": {
    "tracks": ["back camera"]
  }
}
```

常见调用时机：

1. 用户授权摄像头成功：`camera_permission_granted`
2. 用户拒绝摄像头：`camera_permission_denied`
3. 点击开始采集：`stream_started`
4. 点击暂停/停止：`stream_stopped`
5. 相机或上传异常：`capture_error`

响应：`SessionState`。

### 4.9 上传视频帧

```http
POST /api/sessions/{session_id}/frames
Content-Type: application/json
```

请求：

```json
{
  "token": "once_A55u2W2e7pKu8RWz",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...",
  "width": 640,
  "height": 1138,
  "timestamp_ms": 1782570000000,
  "device_motion": {}
}
```

响应：`SessionState`。

客户端建议：

- 每 400-800ms 上传一帧。
- 如果上一帧还在上传，不要并发堆积，跳过或等待下一次。
- 网络失败时延迟 800-1200ms 重试。
- 上传图像宽度建议 640px。
- 使用后置摄像头。
- 食物主体保持在画面中心，大小约占画面 1/3 到 2/3。

后端行为：

- 接收每一帧后立即更新 `latest_frame_url`。
- 分析繁忙时只保留最新待分析帧。
- 通过 WebSocket 推送 `frame_received` 和 `frame_analyzed`。

### 4.10 获取最近帧

```http
GET /api/sessions/{session_id}/latest-frame
```

响应：

- 有帧：`image/jpeg`
- 无帧：`204 No Content`

用途：

- Dashboard 显示手机画面。
- App 调试时查看后端收到的画面。

### 4.11 结束采集并生成报告

```http
POST /api/sessions/{session_id}/finish
```

请求体：无。

响应：`Report`。

示例：

```json
{
  "report_id": "report_18c2",
  "session_id": "sess_20260627_212428_18c2",
  "created_at": "2026-06-27T21:30:00+08:00",
  "meal_summary": {
    "total_weight_g": 129.1,
    "total_weight_error_g": 12.0,
    "total_calories_kcal": 367.7,
    "total_protein_g": 40.0,
    "total_carbs_g": 9.0,
    "total_fat_g": 17.5,
    "overall_confidence": 0.74,
    "convergence": 0.72
  },
  "foods": [
    {
      "track_id": "food_1",
      "name": "炸制鸡胸肉",
      "category": "蛋白质",
      "cooking_method": "deep_fried",
      "cooking_method_name": "炸制",
      "weight_g": 129.1,
      "weight_error_g": 12.0,
      "volume_ml": 126.6,
      "calories_kcal": 367.7,
      "protein_g": 40.0,
      "carbs_g": 9.0,
      "fat_g": 17.5,
      "confidence": 0.74,
      "sample_count": 12,
      "stable_seconds": 8.0,
      "convergence": 0.72
    }
  ],
  "scan_quality": {},
  "warnings": []
}
```

### 4.12 获取报告

```http
GET /api/reports/{report_id}
```

响应：`Report`。

注意：

- 当前 demo 中报告存储在内存中。
- 服务重启后报告丢失。
- 生产环境需要持久化到数据库。

### 4.13 WebSocket 订阅

```text
WS /ws/sessions/{session_id}/events
```

连接成功后，服务端会立即发送：

```json
{
  "type": "state_snapshot",
  "state": {}
}
```

后续事件：

```json
{
  "type": "mobile_connected",
  "state": {}
}
```

```json
{
  "type": "frame_received",
  "state": {}
}
```

```json
{
  "type": "frame_analyzed",
  "state": {}
}
```

```json
{
  "type": "measurement_completed",
  "state": {},
  "report": {}
}
```

客户端建议：

- WebSocket 用于实时 UI。
- 断线后自动重连，并调用 `/state` 拉取最新状态。
- App 页面销毁时关闭 WebSocket。

## 5. App 原生接入伪代码

### 5.1 会话创建

```kotlin
val session = api.createSession()
val sessionId = session.sessionId
val token = session.token

api.joinSession(
    sessionId,
    JoinSessionRequest(
        token = token,
        device = DeviceInfo(
            platform = "android",
            model = Build.MODEL,
            user_agent = "native",
            app_version = BuildConfig.VERSION_NAME
        )
    )
)
```

### 5.2 开始采集

```kotlin
api.captureEvent(sessionId, token, "camera_permission_granted")
api.captureEvent(sessionId, token, "stream_started")

cameraX.onFrame { bitmap ->
    if (uploading) return@onFrame
    val jpegBase64 = encodeJpegBase64(bitmap, width = 640, quality = 65)
    api.uploadFrame(
        sessionId,
        FrameUpload(
            token = token,
            image = "data:image/jpeg;base64,$jpegBase64",
            width = 640,
            height = calculatedHeight,
            timestamp_ms = System.currentTimeMillis(),
            device_motion = mapOf()
        )
    )
}
```

### 5.3 实时结果展示

```kotlin
webSocket.onMessage { message ->
    val event = parseEvent(message)
    val foods = event.state.foods
    val guidance = event.state.guidance.message

    renderFoods(foods.map {
        FoodUi(
            name = it.name,
            weight = it.estimated_weight_g,
            error = it.weight_error_g,
            cooking = it.cooking_method_name,
            scaleStatus = it.scale_status,
            corrected = it.scale_corrected
        )
    })
}
```

## 6. 错误处理

| 状态码 | 场景 | 客户端处理 |
| --- | --- | --- |
| 403 | token 错误或过期 | 重新创建 session |
| 404 | session/report 不存在 | 返回上一页或重新创建 session |
| 422 | 请求体错误或帧解析失败 | 检查 JSON、base64、width/height |
| 204 | latest-frame 暂无图片 | 继续等待 |
| WebSocket 4404 | session 不存在 | 重新创建 session |

上传失败策略：

- 单帧失败不应中断采集。
- 连续失败 3 次以上提示网络问题。
- 可降低帧率或 JPEG 质量后重试。

## 7. 接入验收标准

App 接入后建议按以下标准验收：

1. App 能创建 session 并拿到 token。
2. App 能成功加入 session。
3. App 能完成摄像头授权并上报事件。
4. App 能连续上传 JPEG 帧。
5. 后端 `frame_count` 持续增长。
6. 后端 `analyzed_frame_count` 持续增长。
7. WebSocket 能收到 `frame_analyzed`。
8. `foods` 能返回主体识别结果。
9. 镜头拉近时 `raw_weight_g` 可能变大，但 `estimated_weight_g` 不应同步大幅变大。
10. 镜头拉近/拉远时能看到 `scale_corrected=true` 和对应 `scale_status`。
11. 点击结束后能获取 `Report`。
12. App 展示使用 `estimated_weight_g`，不是 `raw_weight_g`。

## 8. 安全与生产注意事项

当前 demo 的 token 和 session 都是内存态，适合本地验证。生产接入前需要：

- token 绑定用户和业务订单/餐次。
- token 加短 TTL 和签名。
- 所有接口走 HTTPS。
- WebSocket 加鉴权。
- 帧图片和报告做访问控制。
- 日志不要记录完整 base64 图片。
- latest-frame 仅允许当前用户访问。
- 报告持久化到业务数据库。
- 服务重启后能恢复或明确结束 session。
