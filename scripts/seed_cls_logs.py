"""向腾讯云 CLS 主题写入模拟日志，用于验证 AIOps 默认诊断链路。

用法:
    python scripts/seed_cls_logs.py --count 80 --hours 1
    python scripts/seed_cls_logs.py --topic-id <topic_id> --count 30 --wait 15
"""

import argparse
import os
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from tencentcloud.cls.v20201016 import cls_client, models
from tencentcloud.common import credential

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TOPIC_ID = "38754d79-e410-4f16-9ed3-5e047cc8099b"
DEFAULT_REGION = os.getenv("CLS_DEFAULT_REGION", "ap-guangzhou")


def _build_log_classes():
    """按 CLS 官方 pb 协议定义 LogGroupList，wire 格式与官方 proto 兼容。"""
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "cls_seed.proto"
    fdp.package = "cls"
    fdp.syntax = "proto2"

    STR = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    INT64 = descriptor_pb2.FieldDescriptorProto.TYPE_INT64
    MSG = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    REQ = descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED
    OPT = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    REP = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

    def add_msg(name, fields):
        md = fdp.message_type.add()
        md.name = name
        for fname, fnum, ftype, label, type_name in fields:
            field = md.field.add()
            field.name, field.number, field.type, field.label = fname, fnum, ftype, label
            if type_name:
                field.type_name = type_name

    add_msg("Content", [
        ("key", 1, STR, REQ, ""),
        ("value", 2, STR, REQ, ""),
    ])
    add_msg("Log", [
        ("time", 1, INT64, REQ, ""),
        ("contents", 2, MSG, REP, ".cls.Content"),
    ])
    add_msg("LogTag", [
        ("key", 1, STR, REQ, ""),
        ("value", 2, STR, REQ, ""),
    ])
    add_msg("LogGroup", [
        ("logs", 1, MSG, REP, ".cls.Log"),
        ("contextFlow", 2, STR, OPT, ""),
        ("filename", 3, STR, OPT, ""),
        ("source", 4, STR, OPT, ""),
        ("logTags", 5, MSG, REP, ".cls.LogTag"),
    ])
    add_msg("LogGroupList", [
        ("logGroupList", 1, MSG, REP, ".cls.LogGroup"),
    ])

    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    return (
        message_factory.GetMessageClass(pool.FindMessageTypeByName("cls.LogGroupList")),
        message_factory.GetMessageClass(pool.FindMessageTypeByName("cls.LogGroup")),
        message_factory.GetMessageClass(pool.FindMessageTypeByName("cls.Log")),
        message_factory.GetMessageClass(pool.FindMessageTypeByName("cls.Content")),
    )


def _make_log_entries(count: int, hours: int, service: str, now_ms: int):
    """生成时间从旧到新的模拟日志，集中在最近 hours 小时。"""
    entries = []
    start_ms = now_ms - hours * 3600 * 1000
    step_ms = max(1, (now_ms - 60 * 1000 - start_ms) // max(1, count))

    templates = {
        "INFO": [
            "sync_task completed, rows=128",
            "heartbeat ok, worker=worker-01",
            "queue drained, pending=0",
            "config reloaded, version=2026.08.05",
        ],
        "WARN": [
            "sync_task retry scheduled, attempt=2",
            "latency high, duration_ms=1200",
            "queue backlog, pending=342",
            "cpu_usage above 70%, value=73.5",
        ],
        "ERROR": [
            "db connection timeout after 3 retries",
            "sync_task failed, partition offset out of range",
            "cpu_usage exceeded threshold, value=91.2",
            "memory_usage exceeded threshold, value=88.7",
        ],
    }
    weights = [("INFO", 0.45), ("WARN", 0.35), ("ERROR", 0.20)]

    for i in range(count):
        ts = start_ms + i * step_ms
        level = "INFO"
        roll = random.random()
        acc = 0.0
        for name, weight in weights:
            acc += weight
            if roll <= acc:
                level = name
                break

        message = random.choice(templates[level])
        fields = [
            ("level", level),
            ("message", message),
            ("service", service),
            ("source_host", "127.0.0.1"),
        ]
        if level == "ERROR":
            fields.append(("cpu_usage", str(round(random.uniform(80, 98), 1))))
            fields.append(("memory_usage", str(round(random.uniform(70, 95), 1))))
        entries.append((ts, fields))
    return entries


def _upload(client, topic_id: str, entries, LogGroupList, LogGroup, Log, Content):
    """一次上传一个 LogGroup，CLS 会异步建立索引。"""
    group = LogGroup()
    group.filename = "app.log"
    group.source = "127.0.0.1"
    for ts, fields in entries:
        log = group.logs.add()
        log.time = ts
        for key, value in fields:
            content = log.contents.add()
            content.key = key
            content.value = value

    payload = LogGroupList()
    payload.logGroupList.append(group)
    req = models.UploadLogRequest()
    req.TopicId = topic_id
    return client.UploadLog(req, payload.SerializeToString())


def _verify(client, topic_id: str, now_ms: int, wait: int):
    """等待索引建立后，用通配查询确认日志可被搜索到。"""
    print(f"等待 {wait} 秒让 CLS 建立索引...")
    time.sleep(wait)
    req = models.SearchLogRequest()
    req.TopicId = topic_id
    req.From = now_ms - 6 * 3600 * 1000
    req.To = now_ms + 1000
    req.Query = "*"
    req.Limit = 5
    req.Sort = "desc"
    resp = client.SearchLog(req)
    results = resp.Results or []
    print(f"验证完成：最近 6 小时通配查询返回 {len(results)} 条（Limit=5）")
    for item in results:
        print(" ", item.Time, item.LogJson)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="向 CLS 写入模拟日志")
    parser.add_argument("--topic-id", default=TOPIC_ID, help="CLS 日志主题 ID")
    parser.add_argument("--count", type=int, default=80, help="模拟日志条数")
    parser.add_argument("--hours", type=int, default=1, help="日志分布的时间跨度（小时）")
    parser.add_argument("--wait", type=int, default=15, help="上传后等待索引的秒数")
    parser.add_argument("--dry-run", action="store_true", help="只生成日志不上传")
    args = parser.parse_args()

    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID", "")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
    if not secret_id or not secret_key:
        print("缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")
        return

    now_ms = int(time.time() * 1000)
    entries = _make_log_entries(args.count, args.hours, "test", now_ms)
    print(f"生成 {len(entries)} 条模拟日志，时间范围 "
          f"{datetime.fromtimestamp(entries[0][0] / 1000, tz=UTC).astimezone():%H:%M:%S} "
          f"~ {datetime.fromtimestamp(entries[-1][0] / 1000, tz=UTC).astimezone():%H:%M:%S}")

    if args.dry_run:
        print("dry-run：未上传")
        return

    classes = _build_log_classes()
    LogGroupList, LogGroup, Log, Content = classes
    client = cls_client.ClsClient(credential.Credential(secret_id, secret_key), DEFAULT_REGION)
    print(f"上传到主题 {args.topic_id} ...")
    _upload(client, args.topic_id, entries, LogGroupList, LogGroup, Log, Content)
    print("上传成功")
    _verify(client, args.topic_id, now_ms, args.wait)


if __name__ == "__main__":
    main()
