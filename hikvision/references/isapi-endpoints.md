# 海康 ISAPI 端点参考

本文档列出海康威视设备常用的 ISAPI 端点，供开发和调试参考。

## 基础信息

- **协议**: HTTP/HTTPS
- **认证**: Digest 认证（大多数端点）
- **数据格式**: XML（默认）或 JSON
- **基础路径**: `/ISAPI/`

## 系统管理

### 设备信息

```
GET /ISAPI/System/deviceInfo
```

获取设备基本信息，包括型号、序列号、固件版本等。

**响应示例**:

```xml
<DeviceInfo>
    <deviceName>HIKVISION</deviceName>
    <deviceID>001</deviceID>
    <model>DS-7804N-Z1</model>
    <serialNumber>DS7804N-Z123456789</serialNumber>
    <macAddress>c4:2f:90:xx:xx:xx</macAddress>
    <firmwareVersion>V4.61.000</firmwareVersion>
    <firmwareReleasedDate>2023-01-01</firmwareReleasedDate>
</DeviceInfo>
```

### 系统状态

```
GET /ISAPI/System/status
```

获取系统运行状态。

### 网络配置

```
GET /ISAPI/System/Network/interfaces
PUT /ISAPI/System/Network/interfaces
```

查看和修改网络配置。

## 视频流管理

### 通道列表

```
GET /ISAPI/Streaming/Channels
```

获取所有视频通道的配置信息。

**响应示例**:

```xml
<StreamingChannelList>
    <StreamingChannel>
        <id>1</id>
        <channelName>Camera 1</channelName>
        <enabled>true</enabled>
        <Transport>
            <protocol>RTSP</protocol>
        </Transport>
    </StreamingChannel>
</StreamingChannelList>
```

### 单通道配置

```
GET /ISAPI/Streaming/Channels/{id}
PUT /ISAPI/Streaming/Channels/{id}
```

获取或修改指定通道的配置。通道ID格式通常为 `{通道号}01`，如 `101` 表示第1通道的主码流。

### 能力集

```
GET /ISAPI/Streaming/Channels/{id}/capabilities
```

获取通道支持的能力和参数范围。

## 录像管理

### 录像查询

```
POST /ISAPI/ContentMgmt/record/tracks
```

查询指定时间范围内的录像记录。

**请求体**:

```xml
<CMSearchDescription>
    <searchID>...</searchID>
    <trackList>
        <trackID>101</trackID>
    </trackList>
    <timeSpanList>
        <timeSpan>
            <startTime>2026-03-04T00:00:00Z</startTime>
            <endTime>2026-03-04T23:59:59Z</endTime>
        </timeSpan>
    </timeSpanList>
    <maxResults>100</maxResults>
</CMSearchDescription>
```

### 录像状态

```
GET /ISAPI/ContentMgmt/record/tracks/{id}/status
```

获取指定通道的录像状态。

### 回放控制

```
PUT /ISAPI/ContentMgmt/playback/control
```

控制录像回放（播放、暂停、快进等）。

## PTZ 控制

### 连续移动

```
PUT /ISAPI/PTZCtrl/channels/{id}/continuous
```

控制云台连续移动。

**请求体**:

```xml
<PTZData>
    <pan>50</pan>     <!-- 水平: -100 到 100 -->
    <tilt>50</tilt>   <!-- 垂直: -100 到 100 -->
    <zoom>0</zoom>    <!-- 变焦: -100 到 100 -->
</PTZData>
```

### 瞬时移动

```
PUT /ISAPI/PTZCtrl/channels/{id}/momentary
```

控制云台短时间移动后自动停止。

### 预置位

```
GET /ISAPI/PTZCtrl/channels/{id}/presets
PUT /ISAPI/PTZCtrl/channels/{id}/presets/{presetId}
```

管理预置位。

### 巡航

```
GET /ISAPI/PTZCtrl/channels/{id}/patrols
PUT /ISAPI/PTZCtrl/channels/{id}/patrols/{patrolId}/start
```

管理巡航路径。

## 图像抓拍

### 抓图

```
GET /ISAPI/Streaming/Channels/{id}/picture
```

获取指定通道的当前画面截图。

**参数**:
- `videoResolutionWidth`: 图像宽度
- `videoResolutionHeight`: 图像高度

**响应**: JPEG 图像数据

## 事件管理

### 事件订阅

```
POST /ISAPI/Event/notification/subscribe
```

订阅事件通知。

### 事件列表

```
GET /ISAPI/Event/notification/events
```

获取历史事件列表。

**参数**:
- `channelID`: 通道号
- `startTime`: 开始时间
- `endTime`: 结束时间
- `eventType`: 事件类型
- `limit`: 返回数量

### 事件类型

| 事件类型 | 描述 |
|---------|------|
| `videoloss` | 视频丢失 |
| `tampering` | 遮挡报警 |
| `motion` | 移动侦测 |
| `fieldDetection` | 区域入侵 |
| `linedetection` | 越界侦测 |
| `scenechangedetection` | 场景变更 |
| `IO` | IO 报警 |

## 用户管理

### 用户列表

```
GET /ISAPI/System/User
```

获取用户列表。

### 添加用户

```
POST /ISAPI/System/User
```

添加新用户。

### 修改用户

```
PUT /ISAPI/System/User/{username}
```

修改用户信息或密码。

## 存储管理

### 硬盘状态

```
GET /ISAPI/ContentMgmt/Storage/hdd
```

获取硬盘状态信息。

### 格式化硬盘

```
PUT /ISAPI/ContentMgmt/Storage/hdd/{id}/format
```

格式化指定硬盘。

## 常见错误码

| 状态码 | 描述 |
|-------|------|
| 200 | 成功 |
| 400 | 请求格式错误 |
| 401 | 认证失败 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

## 时间格式

ISAPI 使用 ISO 8601 时间格式：

```
2026-03-04T14:30:00Z          # UTC 时间
2026-03-04T14:30:00+08:00     # 带时区
```

## 注意事项

1. **命名空间**: 响应 XML 通常包含命名空间，解析时需要处理
2. **认证**: 大多数端点需要 Digest 认证
3. **HTTPS**: 设备默认使用自签名证书
4. **版本差异**: 不同固件版本可能有 API 差异
5. **并发限制**: 避免同时发送大量请求
