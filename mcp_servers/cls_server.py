"""腾讯云 CLS (Cloud Log Service) MCP Server

提供日志查询、检索和分析功能。
通过腾讯云 CLS API 查询真实日志数据。
"""

import logging
import functools
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastmcp import FastMCP
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.cls.v20201016 import cls_client, models as cls_models

# 加载项目根目录的 .env，读腾讯云密钥
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

TRANSPORT = os.getenv("CLS_TRANSPORT", "sse")
PORT = int(os.getenv("CLS_PORT", "3000"))
HOST = os.getenv("CLS_HOST", "127.0.0.1")
DEFAULT_REGION = os.getenv("CLS_DEFAULT_REGION", "ap-guangzhou")

SECRET_ID = os.getenv("TENCENTCLOUD_SECRET_ID", "")
SECRET_KEY = os.getenv("TENCENTCLOUD_SECRET_KEY", "")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CLS_MCP_Server")

mcp = FastMCP("CLS")


def _get_cls_client(region: Optional[str] = None) -> cls_client.ClsClient:
    """创建腾讯云 CLS 客户端

    Args:
        region: 区域代码，默认从环境变量读取，fallback 到 ap-guangzhou

    Returns:
        ClsClient 实例
    """
    target_region = region or DEFAULT_REGION
    cred = credential.Credential(SECRET_ID, SECRET_KEY)
    return cls_client.ClsClient(cred, target_region)


def _has_credentials() -> bool:
    """检查是否配置了腾讯云密钥"""
    return bool(SECRET_ID and SECRET_KEY)


def log_tool_call(func):
    """装饰器：记录工具调用的日志，包括方法名、参数和返回状态"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = func.__name__

        # 记录调用信息
        logger.info(f"=" * 80)
        logger.info(f"调用方法: {method_name}")

        # 记录参数（排除self等）
        if kwargs:
            # 使用 json.dumps 格式化参数，处理可能的序列化错误
            try:
                params_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_str = str(kwargs)
            logger.info(f"参数信息:\n{params_str}")
        else:
            logger.info("参数信息: 无")

        # 执行方法
        try:
            result = func(*args, **kwargs)

            # 记录返回状态
            logger.info(f"返回状态: SUCCESS")

            # 记录返回结果摘要（避免日志过长）
            if isinstance(result, dict):
                summary = {k: v if not isinstance(v, (list, dict)) else f"<{type(v).__name__} with {len(v)} items>"
                          for k, v in list(result.items())[:5]}
                logger.info(f"返回结果摘要: {json.dumps(summary, ensure_ascii=False)}")
            else:
                logger.info(f"返回结果: {result}")

            logger.info(f"=" * 80)
            return result

        except Exception as e:
            # 记录错误状态
            logger.error(f"返回状态: ERROR")
            logger.error(f"错误信息: {str(e)}")
            logger.error(f"=" * 80)
            raise

    return wrapper


def parse_time_or_default(time_str: Optional[str], default_offset_hours: int = 0) -> datetime:
    """解析时间字符串或返回默认时间。

    Args:
        time_str: 时间字符串（格式：YYYY-MM-DD HH:MM:SS）
        default_offset_hours: 默认时间偏移（小时）

    Returns:
        datetime: 解析后的时间对象
    """
    if time_str:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now() + timedelta(hours=default_offset_hours)


def generate_time_series(base_time: datetime, minutes_offset: int) -> str:
    """生成基于基准时间的时间字符串。

    Args:
        base_time: 基准时间
        minutes_offset: 分钟偏移量

    Returns:
        str: 格式化的时间字符串
    """
    result_time = base_time + timedelta(minutes=minutes_offset)
    return result_time.strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool()
@log_tool_call
def get_current_timestamp() -> int:
    """获取当前时间戳（以毫秒为单位）。
    
    此工具用于获取标准的毫秒时间戳，可用于：
    1. 作为 search_log 的 end_time 参数（查询到现在）
    2. 计算历史时间点作为 start_time 参数
    
    Returns:
        int: 当前时间戳（毫秒），例如: 1708012345000
    
    使用示例:
        # 获取当前时间
        current = get_current_timestamp()
        
        # 计算15分钟前的时间
        fifteen_min_ago = current - (15 * 60 * 1000)
        
        # 计算1小时前的时间
        one_hour_ago = current - (60 * 60 * 1000)
        
        # 用于搜索最近15分钟的日志
        search_log(
            topic_id="topic-001",
            start_time=fifteen_min_ago,
            end_time=current
        )
    """
    return int(datetime.now().timestamp() * 1000)


@mcp.tool()
@log_tool_call
def get_region_code_by_name(region_name: str) -> Dict[str, Any]:
    """根据地区名称搜索对应的地区参数。

    Args:
        region_name: 地区名称（如：北京、上海、广州等）

    Returns:
        Dict: 包含地区代码和相关信息的字典
            - region_code: 地区代码
            - region_name: 地区名称
            - available: 是否可用
    """
    # 模拟地区映射表（实际应该从配置或数据库读取）
    region_mapping = {
        "北京": {"region_code": "ap-beijing", "region_name": "北京", "available": True},
        "上海": {"region_code": "ap-shanghai", "region_name": "上海", "available": True},
        "广州": {"region_code": "ap-guangzhou", "region_name": "广州", "available": True},
    }

    result = region_mapping.get(region_name)
    if result:
        return result
    else:
        return {
            "region_code": None,
            "region_name": region_name,
            "available": False,
            "error": f"未找到地区: {region_name}"
        }


@mcp.tool()
@log_tool_call
def get_topic_info_by_name(topic_name: str, region_code: Optional[str] = None) -> Dict[str, Any]:
    """根据主题名称搜索相关的主题信息。

    Args:
        topic_name: 主题名称
        region_code: 地区代码（可选）

    Returns:
        Dict: 包含主题信息的字典
            - topic_id: 主题ID
            - topic_name: 主题名称
            - region_code: 所属地区
            - create_time: 创建时间
            - log_count: 日志数量
    """
    mock_topics = [
        {
            "topic_id": "topic-001",
            "topic_name": "数据同步服务日志",
            "service_name": "data-sync-service",
            "region_code": "ap-beijing",
            "create_time": "2024-01-01 10:00:00",
            "log_count": 0,
            "description": "服务应用日志"
        }
    ]

    # 根据名称和地区筛选
    for topic in mock_topics:
        if topic["topic_name"] == topic_name:
            if region_code is None or topic["region_code"] == region_code:
                return topic

    return {
        "topic_id": None,
        "topic_name": topic_name,
        "region_code": region_code,
        "error": f"未找到主题: {topic_name}"
    }


@mcp.tool()
@log_tool_call
def search_topic_by_service_name(
    service_name: str,
    region_code: Optional[str] = None,
    fuzzy: bool = True
) -> Dict[str, Any]:
    """根据服务名称搜索相关的日志主题信息，支持模糊搜索。
    
    此工具用于根据服务名称查找对应的日志主题（topic），便于后续进行日志查询。
    
    Args:
        service_name: 服务名称（必填）
            示例: "data-sync-service", "sync", "data-sync"
            说明: 当 fuzzy=True 时，支持部分匹配
        
        region_code: 地区代码（可选）
            示例: "ap-beijing", "ap-shanghai"
            说明: 如果指定，只返回该地区的主题
        
        fuzzy: 是否启用模糊搜索（可选，默认 True）
            True: 部分匹配，例如 "sync" 可以匹配 "data-sync-service"
            False: 精确匹配，必须完全一致
    
    Returns:
        Dict: 搜索结果
            - total: 匹配到的主题数量
            - topics: 主题列表，每个主题包含:
                * topic_id: 主题ID（用于后续日志查询）
                * topic_name: 主题名称
                * service_name: 服务名称
                * region_code: 所属地区
                * create_time: 创建时间
                * log_count: 日志数量
                * description: 主题描述
            - query: 查询条件
    
    使用示例:
        # 示例1: 模糊搜索（推荐）
        search_topic_by_service_name(service_name="data-sync")
        # 可以匹配: "data-sync-service", "data-sync-worker" 等
        
        # 示例2: 精确搜索
        search_topic_by_service_name(
            service_name="data-sync-service",
            fuzzy=False
        )
        
        # 示例3: 指定地区搜索
        search_topic_by_service_name(
            service_name="sync",
            region_code="ap-beijing"
        )
        
        # 示例4: 查找后进行日志搜索的完整流程
        # 步骤1: 根据服务名查找 topic
        result = search_topic_by_service_name(service_name="data-sync-service")
        
        # 步骤2: 获取 topic_id
        topic_id = result["topics"][0]["topic_id"]  # "topic-001"
        
        # 步骤3: 使用 topic_id 查询日志
        current_ts = get_current_timestamp()
        start_ts = current_ts - (15 * 60 * 1000)
        search_log(
            topic_id=topic_id,
            start_time=start_ts,
            end_time=current_ts
        )
    """
    if not _has_credentials():
        logger.warning("腾讯云密钥未配置，无法查询日志主题")
        return {
            "total": 0,
            "topics": [],
            "query": {"service_name": service_name, "region_code": region_code, "fuzzy": fuzzy},
            "message": "腾讯云密钥未配置，请在 .env 中设置 TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY"
        }

    search_region = region_code or DEFAULT_REGION
    client = _get_cls_client(search_region)

    try:
        req = cls_models.DescribeTopicsRequest()
        topic_filter = cls_models.Filter()
        topic_filter.Key = "topicName"
        topic_filter.Values = [service_name]
        req.Filters = [topic_filter]
        req.Offset = 0
        req.Limit = 100

        resp = client.DescribeTopics(req)

        matched_topics = []
        for topic in resp.Topics:
            topic_name = topic.TopicName or ""
            topic_id = topic.TopicId or ""

            if fuzzy:
                if service_name.lower() not in topic_name.lower():
                    continue
            else:
                if topic_name != service_name:
                    continue

            matched_topics.append({
                "topic_id": topic_id,
                "topic_name": topic_name,
                "service_name": topic_name,
                "region_code": search_region,
                "create_time": topic.CreateTime or "",
                "log_count": 0,
                "description": f"日志主题 {topic_name}（{search_region}）"
            })

        if matched_topics:
            return {
                "total": len(matched_topics),
                "topics": matched_topics,
                "query": {"service_name": service_name, "region_code": region_code, "fuzzy": fuzzy},
                "message": f"找到 {len(matched_topics)} 个匹配的日志主题"
            }

        # Fallback: 按主题名没搜到，列出所有可用主题供 Agent 选择
        logger.info(f"按名称 '{service_name}' 未匹配到 topic，列出全部")
        all_req = cls_models.DescribeTopicsRequest()
        all_req.Offset = 0
        all_req.Limit = 100
        all_resp = client.DescribeTopics(all_req)

        all_topics = []
        for topic in all_resp.Topics:
            all_topics.append({
                "topic_id": topic.TopicId or "",
                "topic_name": topic.TopicName or "",
                "service_name": topic.TopicName or "",
                "region_code": search_region,
                "create_time": topic.CreateTime or "",
                "log_count": 0,
                "description": f"日志主题 {topic.TopicName or ''}（{search_region}）"
            })

        return {
            "total": len(all_topics),
            "topics": all_topics,
            "query": {"service_name": service_name, "region_code": region_code, "fuzzy": fuzzy},
            "message": f"按名称未匹配，返回全部 {len(all_topics)} 个可用日志主题"
        }

    except TencentCloudSDKException as e:
        logger.error(f"DescribeTopics 调用失败: {e}")
        return {
            "total": 0,
            "topics": [],
            "query": {"service_name": service_name, "region_code": region_code, "fuzzy": fuzzy},
            "error": f"CLS API 调用失败: {e.message}",
            "message": f"查询失败: {e.message}"
        }


@mcp.tool()
@log_tool_call
def search_log(
    topic_id: str,
    start_time: int,
    end_time: int,
    query: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """基于提供的查询参数搜索日志。

    Args:
        topic_id: 主题ID（必填）
            示例: "topic-001"
        
        start_time: 开始时间戳，单位为毫秒（必填，int类型）
            重要: 必须传递整数类型的毫秒时间戳
            获取方式: 
            1. 使用 get_current_timestamp() 工具获取当前时间戳
            2. 计算历史时间: current_timestamp - (分钟数 * 60 * 1000)
            示例: 
            - 当前时间: 1708012345000
            - 15分钟前: 1708012345000 - (15 * 60 * 1000) = 1708011445000
            - 1小时前: 1708012345000 - (60 * 60 * 1000) = 1708008745000
        
        end_time: 结束时间戳，单位为毫秒（必填，int类型）
            重要: 必须传递整数类型的毫秒时间戳
            通常使用 get_current_timestamp() 工具获取当前时间作为结束时间
            示例: 1708012345000
        
        query: 查询语句（可选，CLS 查询语法）
            示例: "level:ERROR" 或 "message:异常"
        
        limit: 返回结果数量限制（默认100，可选）

    Returns:
        Dict: 搜索结果
            - topic_id: 主题ID
            - start_time: 开始时间戳
            - end_time: 结束时间戳
            - query: 查询语句
            - limit: 结果限制
            - total: 实际返回的日志条数
            - logs: 日志列表，每条日志包含:
                * timestamp: 日志时间（格式: YYYY-MM-DD HH:MM:SS）
                * level: 日志级别
                * message: 日志内容
            - took_ms: 查询耗时（毫秒）
            - message: 查询状态消息
    
    使用示例:
        # 步骤1: 获取当前时间戳
        current_ts = get_current_timestamp()  # 返回: 1708012345000
        
        # 步骤2: 计算开始时间（15分钟前）
        start_ts = current_ts - (15 * 60 * 1000)  # 1708011445000
        
        # 步骤3: 搜索日志
        search_log(
            topic_id="topic-001",
            start_time=start_ts,     # int类型: 1708011445000
            end_time=current_ts,     # int类型: 1708012345000
            limit=100
        )
    """
    if not _has_credentials():
        logger.warning("腾讯云密钥未配置，无法搜索日志")
        return {
            "topic_id": topic_id,
            "start_time": start_time,
            "end_time": end_time,
            "query": query,
            "limit": limit,
            "total": 0,
            "logs": [],
            "took_ms": 0,
            "error": "腾讯云密钥未配置",
            "message": "腾讯云密钥未配置，请在 .env 中设置 TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY"
        }

    client = _get_cls_client(DEFAULT_REGION)

    try:
        req = cls_models.SearchLogRequest()
        req.TopicId = topic_id
        req.From = start_time
        req.To = end_time
        req.Query = query or "*"
        req.Limit = limit
        req.Sort = "desc"

        t_start = time.time()
        resp = client.SearchLog(req)
        t_end = time.time()
        took_ms = int((t_end - t_start) * 1000)

        logs = []
        if resp.Results:
            for result in resp.Results:
                try:
                    parsed = json.loads(result.LogJson) if isinstance(result.LogJson, str) else result.LogJson
                except (json.JSONDecodeError, TypeError):
                    parsed = {"message": str(result.LogJson)}

                log_time = datetime.fromtimestamp(result.Time / 1000) if result.Time else None
                time_str = log_time.strftime("%Y-%m-%d %H:%M:%S") if log_time else ""

                log_entry = {
                    "timestamp": time_str,
                    "timestamp_ms": result.Time,
                    "level": parsed.get("level", ""),
                    "service": parsed.get("service", ""),
                    "message": parsed.get("message", str(parsed)),
                    "source_host": parsed.get("source_host", ""),
                }
                logs.append(log_entry)

        total_found = resp.Analysis and len(resp.AnalysisRecords or [])
        if not total_found:
            total_found = len(logs)

        return {
            "topic_id": topic_id,
            "start_time": start_time,
            "end_time": end_time,
            "query": query,
            "limit": limit,
            "total": len(logs),
            "logs": logs,
            "took_ms": took_ms,
            "message": f"成功查询 {len(logs)} 条日志（耗时 {took_ms}ms）"
        }

    except TencentCloudSDKException as e:
        logger.error(f"SearchLog 调用失败: {e}")
        return {
            "topic_id": topic_id,
            "start_time": start_time,
            "end_time": end_time,
            "query": query,
            "limit": limit,
            "total": 0,
            "logs": [],
            "took_ms": 0,
            "error": f"CLS API 调用失败: {e.message}",
            "message": f"SearchLog 失败: {e.message}"
        }



if __name__ == "__main__":
    print(f"启动 CLS MCP 服务...")
    print(f"传输协议: {TRANSPORT}")
    print(f"监听地址: {HOST}:{PORT}")
    print(f"访问路径: /sse")
    mcp.run(transport=TRANSPORT, host=HOST, port=PORT, path="/sse")
