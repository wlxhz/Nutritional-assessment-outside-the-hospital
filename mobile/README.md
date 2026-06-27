# 慢慢养移动端打包说明

## Android

当前 Android 工程位于 `mobile/android`，是一个原生 WebView 壳应用，默认打开：

```text
https://113.44.105.177/
```

调试包构建命令：

```bash
cd mobile/android
./gradlew assembleDebug
```

本次服务器构建产物已下载到：

```text
outputs/manmanyang-debug.apk
```

调试包为了方便连接当前自签 HTTPS 服务，`MainActivity` 中临时放行了 WebView SSL 错误。正式发布前应改为域名加受信任证书，并移除该调试放行逻辑。

## iOS

iOS 的可安装包 `.ipa` 必须在 macOS 上使用 Xcode、Apple Developer 账号、Bundle ID、证书和 provisioning profile 进行签名构建。当前 Windows 工作站和 Linux 服务器无法直接生成可安装 IPA。

建议路径：

1. 在 macOS 上创建 WKWebView 壳应用，默认加载 `https://113.44.105.177/` 或正式域名。
2. 在 `Info.plist` 配置摄像头、麦克风等权限文案。
3. 使用 Apple Developer 证书进行 Archive 和 Export IPA。
4. 正式环境使用可信 HTTPS 证书，避免相机权限和 ATS 限制问题。
