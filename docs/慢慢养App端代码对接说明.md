# 慢慢养 App 端代码对接说明

## 1. 文档目的

本文档用于整理当前慢慢养 App 端代码，方便后续与视觉识别系统拼接合并。

当前工程中已经同时存在两套能力：

1. 慢慢养 App 业务层：登录、身体指征、营养方案、花园、信息、记录、Agent、短信确认、本地 SQLite。
2. 视觉识别系统：手机采集、视频帧上传、识别 Dashboard、食物克重估算、实时营养反馈。

本文档只说明 App 端代码如何和视觉系统对接，不展开视觉算法内部实现。

## 2. 运行入口

工程目录：

```text
demo/
```

启动命令：

```powershell
cd F:\泉客松\wo-xi\demo
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

App 页面：

```text
http://127.0.0.1:8010
```

视觉系统 Dashboard：

```text
http://127.0.0.1:8010/vision-dashboard
```

手机采集页：

```text
http://127.0.0.1:8010/capture
```

## 3. 代码目录

```text
demo/
  backend/
    main.py
    services/
      mmy_store.py
      mmy_ai.py
      mmy_parser.py
      analyzer.py
      nutrition.py
      session_store.py
  static/
    app.html
    app.css
    app.js
    dashboard.html
    dashboard.js
    capture.html
    capture.js
```

## 4. App 端文件职责

### 4.1 前端页面

| 文件 | 职责 |
| --- | --- |
| `demo/static/app.html` | 慢慢养 App 页面结构，包含登录、花园、信息、记录、视觉预留位 |
| `demo/static/app.css` | 慢慢养 App 样式，白色、米色、简约适老化基调 |
| `demo/static/app.js` | 慢慢养 App 页面逻辑，调用 `/api/mmy/*` 接口 |

### 4.2 后端业务层

| 文件 | 职责 |
| --- | --- |
| `demo/backend/main.py` | FastAPI 入口，同时挂载慢慢养业务接口和视觉系统接口 |
| `demo/backend/services/mmy_store.py` | 慢慢养本地 SQLite 存储层 |
| `demo/backend/services/mmy_ai.py` | 营养方案生成和 Agent 对话的 AI 调用封装 |
| `demo/backend/services/mmy_parser.py` | 本地处方文件解析服务 |

### 4.3 视觉系统侧

| 文件 | 职责 |
| --- | --- |
| `demo/backend/services/analyzer.py` | 视觉分析和食物识别逻辑 |
| `demo/backend/services/session_store.py` | 视觉会话、帧处理、报告生成 |
| `demo/backend/services/nutrition.py` | 食材和营养估算数据 |
| `demo/static/dashboard.html` | 视觉 Dashboard 页面 |
| `demo/static/dashboard.js` | 视觉 Dashboard 逻辑 |
| `demo/static/capture.html` | 手机采集页 |
| `demo/static/capture.js` | 手机采集页逻辑 |

## 5. App 页面结构

### 5.1 登录与配置

位置：

```text
demo/static/app.html
```

DOM 区域：

```html
<section id="onboarding" class="onboarding active">
```

功能：

1. 手机号验证码登录。
2. 手机号一键授权占位。
3. 基础身体指征填写。
4. 保存资料后生成营养方案。

相关 JS：

```text
sendCode()
smsLogin()
oneTapLogin()
collectProfile()
saveProfileAndGenerate()
```

### 5.2 花园页

DOM：

```html
<section id="gardenScreen" class="screen">
```

功能：

1. 展示 7 天周期。
2. 展示小花和大花成长状态。
3. 使用 `/api/mmy/garden/progress` 获取数据。

相关 JS：

```text
refreshGarden()
```

### 5.3 信息页

DOM：

```html
<section id="infoScreen" class="screen">
```

功能：

1. 展示食物贴纸。
2. 展示贴纸颜色图例。
3. 展示视觉识别预留位。
4. 展示营养方案。
5. 展示三餐拆分。
6. 展示红色风险弹窗 Demo。

视觉预留 DOM：

```html
<div class="soft-panel vision-slot">
  <p class="eyebrow">视觉识别预留位</p>
  <h2>等待算法接口接入</h2>
  <button id="visionContractBtn">查看接口契约</button>
  <pre id="visionContract"></pre>
</div>
```

相关 JS：

```text
loadVisionContract()
showRisk()
openSmsFlow()
renderPlan()
```

### 5.4 记录页

DOM：

```html
<section id="recordScreen" class="screen">
```

功能：

1. 日、周、月切换。
2. 饼状图显示占比。
3. 柱状图显示对比。
4. Agent 对话。

相关 JS：

```text
refreshReport()
renderPie()
renderBars()
refreshAgentPrompts()
sendAgentMessage()
```

## 6. 慢慢养业务 API

所有 App 业务接口以 `/api/mmy` 开头。

### 6.1 配置

```http
GET /api/mmy/config
```

用途：

1. 返回本地运行配置。
2. 返回 AI 是否已配置。
3. 返回视觉接口状态。
4. 返回三餐枚举和贴纸颜色。

返回重点字段：

```json
{
  "runtime": "local",
  "storage": "sqlite",
  "aiConfigured": false,
  "vision": {
    "status": "reserved"
  },
  "mealTypes": ["breakfast", "lunch", "dinner"],
  "colors": {
    "compliant": "#9DCF55",
    "generally_compliant": "#EFD67C",
    "non_compliant": "#C82727"
  }
}
```

### 6.2 登录

```http
POST /api/mmy/auth/sms-code/send
POST /api/mmy/auth/sms-code/login
POST /api/mmy/auth/phone-one-tap
```

当前状态：

1. 验证码接口本地返回 `demoCode`。
2. 一键授权接口只打通页面流程。
3. 后续可替换为真实三大运营商 SDK 和验证码发送服务。

### 6.3 用户身体指征

```http
POST /api/mmy/user/profile
GET /api/mmy/user/{user_id}/profile
```

关键字段：

```json
{
  "userId": "user_xxx",
  "diseaseType": "diabetes",
  "weight": 65,
  "height": 168,
  "age": 68,
  "gender": "female",
  "allergyHistory": "无明确过敏史",
  "diseaseHistory": "长期慢病管理需求",
  "workIntensity": "low",
  "emergencyContactPhone": "13900000000"
}
```

### 6.4 处方文件解析

```http
POST /api/mmy/prescriptions/upload
DELETE /api/mmy/prescriptions/{prescription_id}
```

当前实现：

1. `.docx` 真实解析文本。
2. 简单文本 PDF 尝试解析文本。
3. `.doc` 返回需要本地转换工具的反馈。
4. 扫描件 PDF 返回需要 OCR 的反馈。

文件解析服务位置：

```text
demo/backend/services/mmy_parser.py
```

后续拼接点：

1. 接入本地 OCR。
2. 接入 `.doc` 转 `.docx` 或文本工具。
3. 将识别结果结构化为处方预览字段。

### 6.5 营养方案

```http
POST /api/mmy/nutrition-plans/generate
POST /api/mmy/nutrition-plans/from-prescription
GET /api/mmy/users/{user_id}/nutrition-plan
```

AI 封装位置：

```text
demo/backend/services/mmy_ai.py
```

配置文件：

```text
.env
```

配置模板：

```text
.env.example
```

未配置 AI 时：

1. 后端返回本地 fallback 方案。
2. 页面可以正常跑通。
3. 返回 `aiStatus = local_fallback`。

已配置 AI 时：

1. 调用 OpenAI-compatible `/chat/completions`。
2. 返回 `aiStatus = model`。

### 6.6 摄入记录

```http
POST /api/mmy/intake-records
```

这是视觉系统最关键的业务接入口。

当前请求结构：

```json
{
  "userId": "user_xxx",
  "mealType": "breakfast",
  "items": [
    {
      "itemName": "燕麦粥",
      "itemType": "food",
      "grams": 180,
      "complianceLevel": "compliant",
      "nutrients": {
        "energyKcal": 216,
        "proteinG": 7.2,
        "fatG": 3.6,
        "carbohydrateG": 28.8
      }
    }
  ]
}
```

餐次枚举：

```text
breakfast
lunch
dinner
```

贴纸符合程度枚举：

```text
compliant
generally_compliant
non_compliant
```

后端处理：

1. 保存摄入项。
2. 汇总当餐营养素。
3. 判断是否有红色风险食物。
4. 生成下一餐调整占位信息。
5. 写入 SQLite `intake_records`。

### 6.7 报告

```http
GET /api/mmy/reports/nutrients?userId={userId}&rangeType=day
POST /api/mmy/reports/{report_id}/confirm
POST /api/mmy/temp-data/cleanup
```

周期枚举：

```text
day
week
month
```

报告数据结构：

```json
{
  "pieChartData": [],
  "barChartData": [],
  "nutrientSummary": {}
}
```

数据生命周期：

1. 生成报告时写入临时识别数据记录。
2. 用户确认报告后标记临时数据为 `report_confirmed`。
3. 超过 15 分钟未确认时可通过 cleanup 标记为 `expired_15min`。

### 6.8 花园

```http
GET /api/mmy/garden/progress?userId={userId}
```

当前判定逻辑：

1. 有摄入记录。
2. 最近记录中无 `non_compliant` 红色风险项。
3. 生成当天小花状态。

后续可替换为正式规则：

1. 摄入量达标。
2. 记录完整。
3. 无红色风险食物。

### 6.9 Agent

```http
GET /api/mmy/agent/prompts?userId={userId}
POST /api/mmy/agent/messages
GET /api/mmy/agent/messages?userId={userId}
```

当前能力：

1. 主动询问食谱反馈。
2. 主动询问身体感受。
3. 接收用户文字。
4. 调用 AI 或 fallback 回复。

### 6.10 短信确认

```http
POST /api/mmy/sms/confirm
```

用途：

红色风险食物弹窗中，用户确认后拉起系统短信。

返回字段：

```json
{
  "status": "ready_to_open_system_sms",
  "smsUrl": "sms:13900000000?body=..."
}
```

前端处理位置：

```text
openSmsFlow()
```

约束：

1. 必须先弹窗确认。
2. App 不自动发送短信。
3. 用户在系统短信界面手动发送。

## 7. 视觉系统对接契约

### 7.1 契约接口

```http
GET /api/mmy/vision/contract
```

当前返回：

```json
{
  "status": "reserved",
  "expectedResult": {
    "itemName": "品类名称",
    "itemType": "food | medical_food | special_diet",
    "grams": "number",
    "intakeTime": "ISO datetime",
    "nutrientPayload": "用于计算营养摄入的数据",
    "compliancePayload": "用于判断贴纸颜色的数据"
  },
  "stickerColors": {
    "compliant": "#9DCF55",
    "generally_compliant": "#EFD67C",
    "non_compliant": "#C82727"
  }
}
```

### 7.2 视觉系统应输出的数据

视觉系统完成识别后，需要给 App 业务层提供以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `itemName` | string | 食物、特医产品或特膳产品名称 |
| `itemType` | string | `food`、`medical_food`、`special_diet` |
| `grams` | number | 估算克数 |
| `intakeTime` | string | ISO 时间 |
| `nutrients` | object | 可选，营养素数据 |
| `complianceLevel` | string | `compliant`、`generally_compliant`、`non_compliant` |
| `stickerImageUrl` | string | 可选，抠图贴纸图片地址 |
| `stickerColor` | string | 可选，贴纸描边颜色 |
| `confidence` | number | 可选，识别置信度 |
| `sourceSessionId` | string | 可选，对应视觉会话 |
| `sourceTrackId` | string | 可选，对应视觉 track |

### 7.3 推荐提交到 App 的摄入记录格式

视觉系统识别完成后，推荐调用：

```http
POST /api/mmy/intake-records
```

示例：

```json
{
  "userId": "user_xxx",
  "mealType": "lunch",
  "items": [
    {
      "itemName": "清蒸鱼",
      "itemType": "food",
      "grams": 120,
      "intakeTime": "2026-06-27T12:30:00+08:00",
      "complianceLevel": "compliant",
      "stickerColor": "#9DCF55",
      "confidence": 0.86,
      "sourceSessionId": "sess_xxx",
      "sourceTrackId": "food_1",
      "nutrients": {
        "energyKcal": 140,
        "proteinG": 24,
        "fatG": 4,
        "carbohydrateG": 0
      }
    }
  ]
}
```

## 8. 当前视觉系统输出映射

视觉 Dashboard 当前已有 `FoodTrack` 数据，可映射到 App 摄入项。

| 视觉字段 | App 字段 | 说明 |
| --- | --- | --- |
| `FoodTrack.name` | `itemName` | 食物名称 |
| `FoodTrack.estimated_weight_g` | `grams` | 估算克数 |
| `FoodTrack.nutrition.calories_kcal` | `nutrients.energyKcal` | 能量 |
| `FoodTrack.nutrition.protein_g` | `nutrients.proteinG` | 蛋白质 |
| `FoodTrack.nutrition.fat_g` | `nutrients.fatG` | 脂肪 |
| `FoodTrack.nutrition.carbs_g` | `nutrients.carbohydrateG` | 碳水 |
| `FoodTrack.nutrition.fiber_g` | `nutrients.dietaryFiber` | 膳食纤维 |
| `FoodTrack.confidence` | `confidence` | 识别置信度 |
| `FoodTrack.track_id` | `sourceTrackId` | 视觉 track |
| `SessionState.session_id` | `sourceSessionId` | 视觉会话 |

当前视觉系统未直接提供：

1. `complianceLevel`
2. `stickerColor`
3. `stickerImageUrl`
4. `itemType`

这些字段需要由后续规则模块或视觉贴纸模块补齐。

## 9. 前端拼接点

### 9.1 信息页视觉预留位

文件：

```text
demo/static/app.html
```

位置：

```html
<div class="soft-panel vision-slot">
```

当前用途：

1. 展示“等待算法接口接入”。
2. 查看 `/api/mmy/vision/contract`。
3. 后续可替换为摄像头状态、识别结果、贴纸列表或视觉采集入口。

### 9.2 食物贴纸区域

文件：

```text
demo/static/app.html
```

位置：

```html
<div class="sticker-strip">
```

当前是静态示例：

1. 燕麦粥，绿色。
2. 杂粮饭，黄色。
3. 高糖点心，红色。

后续接入视觉系统后，应改为读取识别结果动态渲染。

### 9.3 视觉契约按钮

文件：

```text
demo/static/app.js
```

函数：

```text
loadVisionContract()
```

当前逻辑：

1. 请求 `/api/mmy/vision/contract`。
2. 将接口契约显示在页面上。

后续可替换为：

1. 启动视觉采集会话。
2. 打开手机采集二维码。
3. 展示最新识别结果。

## 10. 后端拼接点

### 10.1 推荐新增桥接接口

目前 App 已有通用摄入接口：

```http
POST /api/mmy/intake-records
```

如果希望视觉系统完成后自动同步到 App，可以新增桥接接口：

```http
POST /api/mmy/vision/intake-sync
```

建议职责：

1. 接收视觉 `session_id`。
2. 读取视觉会话最终报告。
3. 映射 `FoodTrack` 为 App `IntakeItem`。
4. 调用或复用 `mmy_store.save_intake()`。
5. 返回同步后的摄入记录。

### 10.2 当前可复用函数

文件：

```text
demo/backend/main.py
```

可复用逻辑：

```text
_sum_nutrients()
_adjustment_for_items()
_report_data()
```

文件：

```text
demo/backend/services/mmy_store.py
```

可复用存储：

```text
save_intake()
list_intakes()
save_report()
confirm_report()
cleanup_expired_temp_data()
```

## 11. SQLite 表结构

SQLite 文件默认位置：

```text
demo/data/mmy.sqlite
```

该文件是本地运行产物，已被 `.gitignore` 忽略，不应提交。

表：

| 表名 | 用途 |
| --- | --- |
| `users` | 手机号登录用户 |
| `profiles` | 基础身体指征 |
| `prescriptions` | 处方解析结果 |
| `nutrition_plans` | 营养方案 |
| `intake_records` | 摄入记录，视觉系统主要写入目标 |
| `reports` | 日、周、月报告 |
| `agent_messages` | Agent 对话 |
| `temporary_recognition_data` | 识别临时数据生命周期 |

视觉系统重点写入：

```text
intake_records
temporary_recognition_data
reports
```

## 12. 合并步骤建议

### 12.1 第一步：保持两套入口

保留：

```text
/                  慢慢养 App
/vision-dashboard  视觉 Dashboard
/capture           手机采集页
```

这样方便联调时同时查看 App 业务结果和视觉系统原始输出。

### 12.2 第二步：让 App 创建或读取视觉会话

推荐在信息页视觉预留位加入：

1. 创建视觉会话按钮。
2. 手机采集二维码。
3. 最新识别状态。
4. 完成识别后同步到 App 的按钮。

可复用现有视觉接口：

```http
POST /api/sessions
GET /api/sessions/{session_id}/state
POST /api/sessions/{session_id}/finish
GET /api/reports/{report_id}
```

### 12.3 第三步：增加视觉到 App 的同步

新增或复用：

```http
POST /api/mmy/intake-records
```

输入来自视觉报告。

同步后 App 自动刷新：

1. 信息页贴纸。
2. 当餐指标。
3. 风险弹窗。
4. 记录页图表。
5. 花园完成状态。

### 12.4 第四步：补齐规则模块

视觉系统只负责识别和估算，不建议直接决定所有营养规则。

后续需要补齐：

1. `complianceLevel` 判断规则。
2. `stickerColor` 生成规则。
3. 替代食物推荐规则。
4. 下一餐调整规则。
5. 当天和周期剩余可补充量规则。

## 13. 当前边界

1. App 端页面已经可运行，但仍是 Web Demo 形态，不是 React Native 工程。
2. SQLite 存储层已实现，但后续迁移到 React Native 本地 SQLite 时需要换适配器。
3. AI 调用已封装，但真实模型令牌需要写入 `.env`。
4. 文件解析服务已预留本地解析/OCR 扩展点。
5. 视觉识别算法不在 App 页面中实现。
6. 当前 App 页面中贴纸是静态示例，后续需要视觉系统动态驱动。
7. 当前报告图表由本地摄入记录生成，后续应由视觉同步后的真实数据驱动。

## 14. 最小联调清单

视觉系统和 App 端拼接时，最少确认以下事项：

1. 视觉系统最终报告中每个食物是否有稳定 `track_id`。
2. 视觉系统是否能输出食物名称、克数和营养素。
3. 视觉系统是否能区分食物、特医产品、特膳产品。
4. `complianceLevel` 由视觉系统给出，还是由 App 规则模块给出。
5. 贴纸图片由视觉系统生成，还是 App 端根据识别结果生成。
6. 每次视觉会话对应哪个 `userId` 和 `mealType`。
7. 视觉会话完成后是自动同步，还是用户确认后同步。
8. 同步后是否立刻生成报告。
9. 报告确认后如何清理临时视觉数据。
10. 视觉识别失败时在 App 信息页显示什么反馈。
