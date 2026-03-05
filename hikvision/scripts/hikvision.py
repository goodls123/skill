#!/usr/bin/env python3
"""
Hikvision NVR/Camera Controller via ISAPI protocol.

Supports device info, channel management, recording queries,
live stream URLs, PTZ control, snapshots, and event queries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# Try to import requests, provide helpful error if not available
try:
    import requests
    from requests.auth import HTTPDigestAuth
except ImportError:
    print("Error: 'requests' library is required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class HikvisionConfig:
    host: str
    username: str
    password: str
    port: int = 80
    use_https: bool = False
    verify_ssl: bool = False

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @classmethod
    def from_env(cls, host_override: Optional[str] = None) -> "HikvisionConfig":
        host = host_override or os.environ.get("HIKVISION_HOST", "")
        username = os.environ.get("HIKVISION_USER", "")
        password = os.environ.get("HIKVISION_PASSWORD", "")

        if not host:
            raise ValueError("HIKVISION_HOST not set. Use --host or set environment variable.")
        if not username:
            raise ValueError("HIKVISION_USER not set.")
        if not password:
            raise ValueError("HIKVISION_PASSWORD not set.")

        return cls(host=host, username=username, password=password)


class HikvisionClient:
    def __init__(self, config: HikvisionConfig):
        self.config = config
        self.auth = HTTPDigestAuth(config.username, config.password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = config.verify_ssl

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.config.base_url}{path}"
        try:
            resp = self.session.request(method, url, timeout=30, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"无法连接到设备 {self.config.host}: {e}")
        except requests.exceptions.Timeout:
            raise RuntimeError(f"连接超时: {self.config.host}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise RuntimeError("认证失败: 用户名或密码错误")
            raise RuntimeError(f"HTTP错误: {e}")

    def _get(self, path: str) -> requests.Response:
        return self._request("GET", path)

    def _put(self, path: str, data: str, content_type: str = "application/xml") -> requests.Response:
        headers = {"Content-Type": content_type}
        return self._request("PUT", path, data=data, headers=headers)

    def _post(self, path: str, data: str, content_type: str = "application/xml") -> requests.Response:
        headers = {"Content-Type": content_type}
        return self._request("POST", path, data=data, headers=headers)

    def _parse_xml(self, content: bytes) -> ET.Element:
        return ET.fromstring(content)

    def get_device_info(self) -> Dict[str, Any]:
        """获取设备信息"""
        resp = self._get("/ISAPI/System/deviceInfo")
        root = self._parse_xml(resp.content)

        # 定义命名空间
        ns = {"ns": "http://www.hikvision.com/ver20/XMLSchema"}

        info = {}
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            info[tag] = child.text

        return info

    def get_channels(self, debug: bool = False) -> List[Dict[str, Any]]:
        """获取所有通道信息"""
        resp = self._get("/ISAPI/Streaming/Channels")

        if debug:
            print("Raw XML response:", file=sys.stderr)
            print(resp.text[:2000], file=sys.stderr)

        root = self._parse_xml(resp.content)

        channels = []

        # 定义可能的命名空间
        namespaces = [
            "http://www.isapi.org/ver20/XMLSchema",
            "http://www.hikvision.com/ver20/XMLSchema",
        ]

        def parse_element(elem) -> Any:
            """递归解析 XML 元素"""
            children = list(elem)
            if not children:
                return elem.text
            result = {}
            for child in children:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                value = parse_element(child)
                # 如果已有同名标签，转为列表
                if tag in result:
                    if not isinstance(result[tag], list):
                        result[tag] = [result[tag]]
                    result[tag].append(value)
                else:
                    result[tag] = value
            return result

        # 尝试每种命名空间
        for ns in namespaces:
            for channel in root.findall(f".//{{{ns}}}StreamingChannel"):
                ch_info = parse_element(channel)
                if ch_info and isinstance(ch_info, dict):
                    channels.append(ch_info)

        # 如果仍然没有，尝试无命名空间
        if not channels:
            for channel in root.findall(".//StreamingChannel"):
                ch_info = parse_element(channel)
                if ch_info and isinstance(ch_info, dict):
                    channels.append(ch_info)

        # 最后尝试：直接遍历根元素的子元素（忽略命名空间）
        if not channels:
            for elem in root:
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag == "StreamingChannel":
                    ch_info = parse_element(elem)
                    if ch_info and isinstance(ch_info, dict):
                        channels.append(ch_info)

        return channels

    def get_stream_url(self, channel_id: int) -> Dict[str, Any]:
        """获取指定通道的流地址"""
        resp = self._get(f"/ISAPI/Streaming/Channels/{channel_id}01")
        root = self._parse_xml(resp.content)

        info = {}
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            info[tag] = child.text

        # 构建RTSP URL
        if "id" in info:
            ch_num = int(info["id"]) // 100
            rtsp_url = f"rtsp://{self.config.username}:{self.config.password}@{self.config.host}:554/Streaming/Channels/{ch_num}01"
            info["rtspUrl"] = rtsp_url

        return info

    def query_records(
        self, channel_id: int, start_time: str, end_time: str
    ) -> List[Dict[str, Any]]:
        """查询录像记录"""
        # ISAPI 录像查询使用 POST 请求
        query_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<CMSearchDescription>
    <searchID>C7B193D7-6357-4C97-A7E9-E5B4C9B5A1B3</searchID>
    <trackList>
        <trackID>{channel_id}01</trackID>
    </trackList>
    <timeSpanList>
        <timeSpan>
            <startTime>{start_time}</startTime>
            <endTime>{end_time}</endTime>
        </timeSpan>
    </timeSpanList>
    <maxResults>100</maxResults>
    <searchResultPostion>0</searchResultPostion>
    <metadataList>
        <metadataDescriptor>//metadata.psia.org/VideoMotion</metadataDescriptor>
    </metadataList>
</CMSearchDescription>"""

        try:
            resp = self._post("/ISAPI/ContentMgmt/record/tracks", query_xml)
            root = self._parse_xml(resp.content)

            records = []
            for match in root.findall(".//{http://www.hikvision.com/ver20/XMLSchema}searchMatchItem"):
                record = {}
                for child in match:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    record[tag] = child.text
                records.append(record)

            # 无命名空间解析
            if not records:
                for match in root.findall(".//searchMatchItem"):
                    record = {}
                    for child in match:
                        record[child.tag] = child.text
                    records.append(record)

            return records
        except RuntimeError:
            # 某些设备可能不支持此接口
            return []

    def ptz_control(
        self, channel_id: int, action: str, speed: int = 50
    ) -> bool:
        """PTZ 云台控制"""
        # 映射动作到水平和垂直参数
        action_map = {
            "up": (0, speed),
            "down": (0, -speed),
            "left": (-speed, 0),
            "right": (speed, 0),
            "zoom_in": (0, 0, speed),
            "zoom_out": (0, 0, -speed),
            "stop": (0, 0, 0),
        }

        if action not in action_map:
            raise ValueError(f"无效的PTZ动作: {action}")

        params = action_map[action]

        if action == "stop":
            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<PTZData>
    <pan>0</pan>
    <tilt>0</tilt>
    <zoom>0</zoom>
</PTZData>"""
        elif action in ["zoom_in", "zoom_out"]:
            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<PTZData>
    <pan>0</pan>
    <tilt>0</tilt>
    <zoom>{params[2]}</zoom>
</PTZData>"""
        else:
            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<PTZData>
    <pan>{params[0]}</pan>
    <tilt>{params[1]}</tilt>
    <zoom>0</zoom>
</PTZData>"""

        try:
            self._put(f"/ISAPI/PTZCtrl/channels/{channel_id}/continuous", xml_data)
            return True
        except RuntimeError:
            # 尝试另一种端点格式
            try:
                self._put(f"/ISAPI/PTZCtrl/channels/{channel_id}/momentary", xml_data)
                return True
            except RuntimeError:
                return False

    def take_snapshot(self, channel_id: int, output_path: Optional[str] = None) -> str:
        """抓取快照

        channel_id: 可以是物理通道号（如 2）或流通道号（如 201）
        """
        # 尝试多种端点格式
        endpoints = [
            f"/ISAPI/Streaming/Channels/{channel_id}/picture",           # 直接使用传入的ID
            f"/ISAPI/Streaming/Channels/{channel_id}01/picture",         # 添加码流后缀
            f"/ISAPI/Streaming/channels/{channel_id}/picture",           # 小写
            f"/ISAPI/System/Video/inputs/channels/{channel_id}/picture", # 另一种格式
        ]

        last_error = None
        for endpoint in endpoints:
            try:
                resp = self._get(endpoint)
                if output_path is None:
                    import tempfile
                    output_path = tempfile.mktemp(suffix=".jpg")

                with open(output_path, "wb") as f:
                    f.write(resp.content)

                return output_path
            except RuntimeError as e:
                last_error = e
                continue

        raise RuntimeError(f"抓图失败: {last_error}")

    def get_events(self, channel_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """获取报警事件"""
        # 注意：此接口因设备而异，某些设备可能不支持
        try:
            if channel_id:
                resp = self._get(f"/ISAPI/Event/notification/events?channelID={channel_id}&limit={limit}")
            else:
                resp = self._get(f"/ISAPI/Event/notification/events?limit={limit}")

            root = self._parse_xml(resp.content)

            events = []
            for event in root.findall(".//{http://www.hikvision.com/ver20/XMLSchema}EventNotificationAlert"):
                ev = {}
                for child in event:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    ev[tag] = child.text
                events.append(ev)

            if not events:
                for event in root.findall(".//EventNotificationAlert"):
                    ev = {}
                    for child in event:
                        ev[child.tag] = child.text
                    events.append(ev)

            return events[:limit]
        except RuntimeError:
            return []


def format_device_info(info: Dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(info, indent=2, ensure_ascii=False)

    lines = ["设备信息:"]
    key_names = {
        "deviceName": "设备名称",
        "deviceID": "设备ID",
        "deviceDescription": "设备描述",
        "model": "型号",
        "serialNumber": "序列号",
        "macAddress": "MAC地址",
        "firmwareVersion": "固件版本",
        "firmwareReleasedDate": "固件发布日期",
        "encoderVersion": "编码器版本",
        "encoderReleasedDate": "编码器发布日期",
        "bootVersion": "引导版本",
        "bootReleasedDate": "引导发布日期",
        "hardwareVersion": "硬件版本",
        "systemContact": "系统联系人",
    }

    for key, value in info.items():
        label = key_names.get(key, key)
        lines.append(f"  {label}: {value}")

    return "\n".join(lines)


def format_channels(channels: List[Dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(channels, indent=2, ensure_ascii=False)

    lines = ["摄像头通道:"]
    for ch in channels:
        ch_id = ch.get("id", "?")
        ch_name = ch.get("channelName", f"通道 {ch_id}")
        enabled = ch.get("enabled", "unknown")
        lines.append(f"  [{ch_id}] {ch_name} (状态: {enabled})")

    return "\n".join(lines)


def format_stream_url(info: Dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(info, indent=2, ensure_ascii=False)

    lines = ["流地址信息:"]
    for key, value in info.items():
        lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def format_records(records: List[Dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(records, indent=2, ensure_ascii=False)

    if not records:
        return "未找到录像记录"

    lines = ["录像记录:"]
    for rec in records:
        start = rec.get("startTime", "?")
        end = rec.get("endTime", "?")
        track = rec.get("trackID", "?")
        lines.append(f"  通道 {track}: {start} - {end}")

    return "\n".join(lines)


def format_events(events: List[Dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(events, indent=2, ensure_ascii=False)

    if not events:
        return "未找到报警事件"

    lines = ["报警事件:"]
    for ev in events:
        ch = ev.get("channelID", "?")
        ev_type = ev.get("eventType", "?")
        time = ev.get("dateTime", "?")
        lines.append(f"  通道 {ch}: {ev_type} @ {time}")

    return "\n".join(lines)


def main() -> int:
    # 共享参数（用于子命令继承）
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--host", help="录像机IP地址 (默认从 HIKVISION_HOST 环境变量读取)")
    parent_parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    parent_parser.add_argument("--debug", action="store_true", help="显示调试信息")

    parser = argparse.ArgumentParser(
        description="海康威视录像机控制器 (ISAPI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[parent_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # device-info
    subparsers.add_parser("device-info", help="获取设备信息", parents=[parent_parser])

    # channels
    subparsers.add_parser("channels", help="列出所有通道", parents=[parent_parser])

    # stream-url
    stream_parser = subparsers.add_parser("stream-url", help="获取实时流地址", parents=[parent_parser])
    stream_parser.add_argument("--channel", type=int, required=True, help="通道号")
    stream_parser.add_argument("--all", action="store_true", help="获取所有通道")

    # records
    records_parser = subparsers.add_parser("records", help="查询录像", parents=[parent_parser])
    records_parser.add_argument("--channel", type=int, required=True, help="通道号")
    records_parser.add_argument("--start", required=True, help="开始时间 (格式: YYYY-MM-DD HH:MM:SS)")
    records_parser.add_argument("--end", required=True, help="结束时间 (格式: YYYY-MM-DD HH:MM:SS)")

    # ptz
    ptz_parser = subparsers.add_parser("ptz", help="PTZ云台控制", parents=[parent_parser])
    ptz_parser.add_argument("--channel", type=int, required=True, help="通道号")
    ptz_parser.add_argument(
        "--action",
        required=True,
        choices=["up", "down", "left", "right", "zoom_in", "zoom_out", "stop"],
        help="动作",
    )
    ptz_parser.add_argument("--speed", type=int, default=50, help="移动速度 (0-100)")

    # snapshot
    snapshot_parser = subparsers.add_parser("snapshot", help="抓取快照", parents=[parent_parser])
    snapshot_parser.add_argument("--channel", type=int, required=True, help="通道号")
    snapshot_parser.add_argument("--output", help="输出文件路径")

    # events
    events_parser = subparsers.add_parser("events", help="查询报警事件", parents=[parent_parser])
    events_parser.add_argument("--channel", type=int, help="通道号")
    events_parser.add_argument("--limit", type=int, default=10, help="返回数量限制")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        config = HikvisionConfig.from_env(args.host)
    except ValueError as e:
        eprint(str(e))
        return 1

    client = HikvisionClient(config)

    try:
        if args.command == "device-info":
            info = client.get_device_info()
            print(format_device_info(info, args.format))

        elif args.command == "channels":
            channels = client.get_channels(debug=args.debug)
            print(format_channels(channels, args.format))

        elif args.command == "stream-url":
            if args.all:
                channels = client.get_channels()
                for ch in channels:
                    ch_id = int(ch.get("id", 0)) // 100
                    if ch_id > 0:
                        info = client.get_stream_url(ch_id)
                        print(format_stream_url(info, args.format))
            else:
                info = client.get_stream_url(args.channel)
                print(format_stream_url(info, args.format))

        elif args.command == "records":
            records = client.query_records(args.channel, args.start, args.end)
            print(format_records(records, args.format))

        elif args.command == "ptz":
            success = client.ptz_control(args.channel, args.action, args.speed)
            if success:
                print(f"PTZ控制成功: {args.action}")
            else:
                eprint("PTZ控制失败: 设备可能不支持此功能")
                return 2

        elif args.command == "snapshot":
            output = client.take_snapshot(args.channel, args.output)
            print(f"快照已保存: {output}")

        elif args.command == "events":
            events = client.get_events(args.channel, args.limit)
            print(format_events(events, args.format))

        return 0

    except RuntimeError as e:
        eprint(str(e))
        return 2
    except Exception as e:
        eprint(f"错误: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
