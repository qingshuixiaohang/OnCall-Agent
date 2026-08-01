"""
上传测试日志到腾讯云 CLS（使用主 SDK，不依赖 tencentcloud-cls-sdk-python）

使用 tencentcloud-sdk-python 的 UploadLog API，手动编写 protobuf 编码，
避免 protobuf 版本冲突（项目用 v6，CLS Log SDK 需要 v3）。
"""
import os
import sys
import json
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.cls.v20201016 import cls_client, models as cls_models

load_dotenv()

SECRET_ID = os.environ.get("TENCENTCLOUD_SECRET_ID", "")
SECRET_KEY = os.environ.get("TENCENTCLOUD_SECRET_KEY", "")
REGION = "ap-guangzhou"
TOPIC_ID = "38754d79-e410-4f16-9ed3-5e047cc8099b"

# ============================================================================
# Protobuf 手动编码（CLS 日志上传格式）
# 文档: https://cloud.tencent.com/document/product/614/16873
# ============================================================================

def _varint(value: int) -> bytes:
    """编码 varint"""
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _tag(field_number: int, wire_type: int) -> bytes:
    """编码 field tag"""
    return _varint((field_number << 3) | wire_type)


def _field_int64(field_number: int, value: int) -> bytes:
    """编码 int64 字段（wire type 0）"""
    return _tag(field_number, 0) + _varint(value)


def _field_bytes(field_number: int, data: bytes) -> bytes:
    """编码 length-delimited 字段（wire type 2）"""
    return _tag(field_number, 2) + _varint(len(data)) + data


def _field_string(field_number: int, value: str) -> bytes:
    """编码 string 字段"""
    return _field_bytes(field_number, value.encode("utf-8"))


def encode_content(key: str, value: str) -> bytes:
    """编码 Content 消息: { key=1, value=2 }"""
    return _field_string(1, key) + _field_string(2, value)


def encode_log(timestamp_ms: int, contents: dict) -> bytes:
    """编码 Log 消息: { time=1(int64), contents=2(repeated Content) }"""
    data = _field_int64(1, timestamp_ms)
    for key, value in contents.items():
        data += _field_bytes(2, encode_content(key, str(value)))
    return data


def encode_log_group(logs: list, source: str = "10.0.0.1") -> bytes:
    """编码 LogGroup 消息: { logs=1(repeated Log), source=4(string) }"""
    data = b""
    for log_data in logs:
        data += _field_bytes(1, log_data)
    if source:
        data += _field_string(4, source)
    return data


def encode_log_group_list(log_groups: list) -> bytes:
    """编码 LogGroupList 消息: { logGroupList=1(repeated LogGroup) }"""
    data = b""
    for group_data in log_groups:
        data += _field_bytes(1, group_data)
    return data


# ============================================================================
# 日志数据
# ============================================================================

ALL_LOGS = [
    # ========== data-sync-service ==========
    ("ERROR",   "data-sync-service", "数据库连接超时: connection to mysql://10.0.1.50:3306 timed out after 30s", -5),
    ("ERROR",   "data-sync-service", "数据同步失败: batch #28471 写入目标库失败，已重试3次", -8),
    ("ERROR",   "data-sync-service", "Kafka 消费者异常: offset reset, partition=3 lag=15000", -12),
    ("WARNING", "data-sync-service", "同步延迟上升: 当前延迟 45s，阈值 30s", -3),
    ("WARNING", "data-sync-service", "批量大小超限: batch #28472 包含 12000 条记录，建议拆分", -7),
    ("INFO",    "data-sync-service", "增量同步任务开始，源库 binlog 位置: mysql-bin.000042:7845123", -10),
    ("INFO",    "data-sync-service", "全量同步完成: 共同步 1,250,000 条记录，耗时 8m32s", -15),
    ("INFO",    "data-sync-service", "连接池状态: active=12, idle=8, max=20", -1),
    ("DEBUG",   "data-sync-service", "检查点保存成功: checkpoint_id=ck_20250120_003", -6),

    # ========== web-server ==========
    ("ERROR",   "web-server", "HTTP 500 Internal Server Error: /api/v1/orders/create - NullPointerException at OrderService.java:156", -2),
    ("ERROR",   "web-server", "HTTP 502 Bad Gateway: 上游服务 user-service 无响应 (10.0.2.20:8080)", -6),
    ("ERROR",   "web-server", "HTTP 504 Gateway Timeout: /api/v1/reports/generate 请求处理超时 60s", -15),
    ("ERROR",   "web-server", "线程池耗尽: activeThreads=200, maxThreads=200, 队列积压=350", -20),
    ("WARNING", "web-server", "QPS 急剧上升: 当前 8500/s，较5分钟前增长 320%", -4),
    ("WARNING", "web-server", "响应时间 P99 超过 3s: /api/v1/products/search 平均 2.8s", -9),
    ("WARNING", "web-server", "Session 存储 Redis 连接异常，切换到本地缓存模式", -14),
    ("INFO",    "web-server", "服务启动完成，监听端口 8080，注册到 Nacos 成功", -25),
    ("INFO",    "web-server", "健康检查通过: /health 返回 200", -1),
    ("INFO",    "web-server", "优雅关闭: 已排空 45 个进行中请求", -30),

    # ========== database ==========
    ("ERROR",   "database", "主从复制中断: Slave_IO_Running=No, 错误: Got fatal error 1236 from master", -7),
    ("ERROR",   "database", "死锁检测: transaction id=8842912, 等待锁表 orders, 持有锁表 inventory", -11),
    ("ERROR",   "database", "磁盘空间不足: /data/mysql 使用率 92%，数据库写入被阻塞", -18),
    ("CRITICAL","database", "主库宕机! 触发 MHA 自动故障转移，切换到从库 10.0.1.52", -22),
    ("WARNING", "database", "连接池使用率: 85/100, 建议扩容", -5),
    ("WARNING", "database", "慢查询告警: SELECT * FROM orders WHERE status='pending' ORDER BY created_at 耗时 12.5s", -3),
    ("WARNING", "database", "临时表空间使用: /tmp 目录使用率 78%", -13),
    ("INFO",    "database", "备份任务完成: 全量备份大小 15.2GB, 耗时 42m", -24),
    ("INFO",    "database", "索引重建完成: orders.idx_status_created 重建耗时 3m20s", -16),

    # ========== api-gateway ==========
    ("ERROR",   "api-gateway", "限流触发: /api/v1/payment 接口被限流，拒绝 120 个请求", -8),
    ("ERROR",   "api-gateway", "SSL 证书即将过期: *.example.com 证书还有 3 天到期", -28),
    ("WARNING", "api-gateway", "上游服务降级: inventory-service 响应时间 > 2s，触发熔断", -6),
    ("WARNING", "api-gateway", "请求体过大: /api/v1/upload 接收 15MB，超过限制 10MB", -10),
    ("INFO",    "api-gateway", "路由刷新完成: 加载 42 条路由规则", -20),
    ("INFO",    "api-gateway", "灰度发布: v2.3.0 版本流量占比调整为 30%", -17),

    # ========== cache-service (Redis) ==========
    ("ERROR",   "cache-service", "Redis 内存溢出: used_memory=8.5GB, maxmemory=8GB, 写入被拒绝", -4),
    ("ERROR",   "cache-service", "Redis Cluster 节点 10.0.3.12:6379 失联超过 30s", -12),
    ("WARNING", "cache-service", "缓存命中率下降: 从 95% 降至 72%，大量请求穿透到数据库", -9),
    ("WARNING", "cache-service", "大 Key 扫描: user:sessions 占用 450MB, 建议拆分", -15),
    ("INFO",    "cache-service", "缓存预热完成: 预加载 500,000 个热点 Key", -26),

    # ========== auth-service ==========
    ("ERROR",   "auth-service", "LDAP 认证服务不可用: ldap://10.0.5.10:389 连接被拒绝", -6),
    ("ERROR",   "auth-service", "JWT 签名密钥轮换失败: 新密钥分发到 3/5 节点后超时", -14),
    ("WARNING", "auth-service", "登录失败率异常: 最近5分钟失败率 25%，正常值 < 5%", -3),
    ("WARNING", "auth-service", "Token 过期清理: 累积过期 token 12,000 个待清理", -11),
    ("INFO",    "auth-service", "OAuth2 客户端注册: 新增客户端 app-id=order_app_v2", -22),

    # ========== monitoring ==========
    ("ERROR",   "monitoring", "CPU 使用率持续高于 95%: web-server 节点 10.0.2.10 已持续 10 分钟", -5),
    ("ERROR",   "monitoring", "内存使用率超过 90%: database 节点 10.0.1.50 已触发 OOM Killer", -10),
    ("ERROR",   "monitoring", "磁盘空间告警: /var/log 分区使用率 95%，日志写入即将失败", -13),
    ("WARNING", "monitoring", "网络丢包率上升: eth0 接口丢包率 3.2%，正常 < 0.1%", -8),
    ("WARNING", "monitoring", "文件描述符使用率: web-server 进程 fd 使用量 8500/10000", -7),
    ("INFO",    "monitoring", "Prometheus 指标采集正常: 当前采集 1,250 个 target", -1),
    ("INFO",    "monitoring", "告警规则更新: 新增 CPU 持续高负载告警规则", -25),

    # ========== 混合场景 ==========
    ("ERROR",   "web-server", "请求参数校验失败: /api/v1/orders body 缺少必填字段 customer_id", -1),
    ("ERROR",   "web-server", "第三方支付回调验签失败: 来自 203.0.113.50 的请求签名不匹配", -9),
    ("WARNING", "api-gateway", "不安全的 API 调用: /api/v1/admin 从外网 IP 203.0.113.99 访问", -4),
    ("INFO",    "web-server", "A/B 测试: feature_new_checkout 分配比例调整为 50%:50%", -3),
    ("DEBUG",   "data-sync-service", "消息确认: offset=489201, partition=2, lag=0", -2),
    ("ERROR",   "database", "查询优化器选择错误索引: orders 表全表扫描 2,300,000 行", -16),
    ("WARNING", "auth-service", "密码强度策略更新: 新密码需包含大小写字母+数字+特殊字符", -19),
    ("INFO",    "monitoring", "日志归档: 归档 30 天前日志 45GB 到对象存储", -22),
    ("CRITICAL","monitoring", "Kubernetes 节点 NotReady: node-12 状态异常，Pod 正在驱逐", -5),
    ("ERROR",   "cache-service", "Redis RDB 持久化失败: fork 时内存不足，bgsave 被终止", -13),
    ("INFO",    "web-server", "配置热更新: 数据库连接池 max-size 从 50 调整为 100", -7),
    ("WARNING", "web-server", "请求频率异常: IP 198.51.100.25 发起 5000 次/min 疑似爬虫", -2),
    ("DEBUG",   "api-gateway", "路由匹配: /api/v2/orders/* 匹配到 order-service-v2 集群", -6),
]


def get_timestamp_ms(minutes_ago: int) -> int:
    """根据'多少分钟前'计算毫秒时间戳"""
    target_time = datetime.now() + timedelta(minutes=minutes_ago)
    return int(round(target_time.timestamp() * 1000))


def build_protobuf_body() -> bytes:
    """构建 CLS UploadLog 需要的 protobuf 二进制数据"""
    encoded_logs = []
    for level, service, message, minutes_ago in ALL_LOGS:
        timestamp_ms = get_timestamp_ms(minutes_ago)
        contents = {
            "level": level,
            "service": service,
            "message": message,
            "source_host": f"10.0.{abs(hash(service)) % 256}.{abs(hash(message)) % 256}",
        }
        encoded_logs.append(encode_log(timestamp_ms, contents))

    log_group = encode_log_group(encoded_logs, source="10.0.0.1")
    log_group_list = encode_log_group_list([log_group])
    return log_group_list


def upload_logs():
    """使用主 SDK 上传日志"""
    if not SECRET_ID or not SECRET_KEY:
        print("ERROR: TENCENTCLOUD_SECRET_ID/KEY not configured in .env")
        return 0

    cred = credential.Credential(SECRET_ID, SECRET_KEY)
    client = cls_client.ClsClient(cred, REGION)

    body = build_protobuf_body()
    print(f"   - Protobuf body size: {len(body)} bytes")

    try:
        req = cls_models.UploadLogRequest()
        req.TopicId = TOPIC_ID

        resp = client.UploadLog(req, body)
        print(f"   - Request ID: {resp.RequestId}")
        return len(ALL_LOGS)

    except TencentCloudSDKException as e:
        print(f"   - Upload FAILED: {e.message}")
        if hasattr(e, "code"):
            print(f"   - Error code: {e.code}")
        return 0


if __name__ == "__main__":
    print("Uploading logs to Tencent Cloud CLS...")
    print(f"   - Region: {REGION}")
    print(f"   - Topic ID: {TOPIC_ID}")
    print(f"   - Total logs: {len(ALL_LOGS)}")
    services = set(log[1] for log in ALL_LOGS)
    levels = set(log[0] for log in ALL_LOGS)
    print(f"   - Services: {', '.join(sorted(services))}")
    print(f"   - Levels: {', '.join(sorted(levels))}")
    print()

    count = upload_logs()
    if count:
        print(f"\nUpload success! {count} logs uploaded.")
        print(f"\nNext steps:")
        print(f"   1. Start CLS MCP server: uv run python mcp_servers/cls_server.py")
        print(f"   2. Try these queries with AIOps Agent:")
        print(f"      - 'data-sync-service 最近有什么 ERROR 日志？'")
        print(f"      - 'database 主库是不是挂了？'")
        print(f"      - 'web-server 有哪些异常？'")
    else:
        print("\nUpload failed.")