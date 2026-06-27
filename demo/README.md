# 基于长时间视频的食物克重识别与实时营养反馈系统 Demo

这是按 `outputs/基于长时间视频的食物克重识别与实时营养反馈系统技术文档.md` 重建的第一版全栈 demo。

## 已开发内容

- FastAPI 后端：会话、token、二维码、手机加入、采集事件、JPEG 帧上传、实时状态、最终报告。
- WebSocket：Dashboard 订阅 `/ws/sessions/{session_id}/events`，实时接收分析结果。
- Android 手机采集页：`getUserMedia` 摄像头授权，Canvas 抽帧，JPEG 上传。
- Dashboard：实时显示手机画面、bbox、mask、多目标 track、克重、误差、置信度、营养汇总、测量质量、报告。
- 识别算法：优先加载 `models/yolo11n-seg.pt` 走 YOLOv11 segmentation；模型不可用时自动使用 OpenCV/numpy fallback。
- 营养和估重：按食物密度库计算体积、克重、热量、蛋白质、碳水、脂肪。

## 安装依赖

```powershell
cd F:\泉客松\wo-xi\demo
python -m pip install -r requirements.txt
```

如果 `ultralytics` 或模型依赖安装失败，仍可以先运行服务；系统会使用 OpenCV fallback 算法。

## 下载 YOLOv11 分割模型

```powershell
cd F:\泉客松\wo-xi\demo
python scripts/download_yolo11.py
```

模型文件会放到：

```text
F:\泉客松\wo-xi\demo\models\yolo11n-seg.pt
```

如需 food 专用模型，把 `.pt` 文件放到 `demo/models/`，然后设置环境变量：

```powershell
$env:FOOD_MODEL_PATH="F:\泉客松\wo-xi\demo\models\your-food-model.pt"
python run_http.py
```

## 本地电脑测试

```powershell
cd F:\泉客松\wo-xi\demo
python run_http.py
```

打开：

```text
http://127.0.0.1:8000
```

## Android 真机摄像头授权测试

Android Chrome 对摄像头通常要求安全上下文。手机访问电脑 IP 的普通 HTTP 地址时，可能不会允许摄像头授权。

先生成开发证书：

```powershell
cd F:\泉客松\wo-xi\demo
python scripts/generate_dev_cert.py
```

启动 HTTPS：

```powershell
python run_https.py
```

电脑 Dashboard 打开：

```text
https://127.0.0.1:8443
```

手机和电脑连接同一 Wi-Fi，使用脚本输出的局域网地址，例如：

```text
https://192.168.x.x:8443
```

首次访问自签名证书会有浏览器安全提示，需要在测试手机上继续访问或安装信任证书。生产或内网穿透测试建议使用正式 HTTPS 域名。

## 使用流程

1. 打开 Dashboard。
2. 系统自动创建 session 和二维码。
3. Android 手机扫码打开采集页。
4. 点击“连接会话”。
5. 点击“授权摄像头”。
6. 点击“开始推流”。
7. Dashboard 看到手机画面、识别框、mask、克重、营养和质量指标。
8. 点击“生成报告”输出最终 JSON 报告。

## API 摘要

- `POST /api/sessions`
- `GET /api/sessions/{session_id}/qrcode`
- `POST /api/sessions/{session_id}/join`
- `POST /api/sessions/{session_id}/capture-event`
- `POST /api/sessions/{session_id}/frames`
- `GET /api/sessions/{session_id}/state`
- `GET /api/sessions/{session_id}/latest-frame`
- `POST /api/sessions/{session_id}/finish`
- `GET /api/reports/{report_id}`
- `WS /ws/sessions/{session_id}/events`

## 当前边界

第一版用于技术链路验证。普通 RGB 视频无法直接获得真实重量，本 demo 会输出误差和置信度。YOLOv11 官方模型不一定能准确识别所有中餐具体菜名；food 专用模型可以通过 `FOOD_MODEL_PATH` 替换。
