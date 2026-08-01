# 中间件故障告警处理方案

## 告警名称
- **告警名**: `MiddlewareFailure`
- **告警级别**: 严重
- **触发条件**: Redis、MQ、ES等中间件服务异常或性能下降

## 问题描述
中间件故障会导致：
- 缓存失效，数据库压力增大
- 消息队列阻塞，异步处理失败
- 搜索服务不可用
- 系统性能下降
- 业务功能异常

## 排查步骤

### 步骤1: 获取当前时间
**工具**: `get_current_time`
**目的**: 确定故障发生时间

### 步骤2: 查询中间件监控日志
**工具**: `query_logs`
**参数要求**:
- **地域**: `ap-guangzhou`
- **日志主题**: `middleware-metrics`
- **时间范围**: 最近30分钟
- **查询条件**: `service:redis OR service:rabbitmq OR service:elasticsearch`

**查询示例**:
```
地域: ap-guangzhou
日志主题: middleware-metrics
时间范围: [当前时间-30分钟] 到 [当前时间]
查询语句: (service:redis OR service:rabbitmq) AND status:error
```

### 步骤3: 查询应用中间件调用日志
**工具**: `query_logs`
**参数要求**:
- **日志主题**: `application-logs`
- **查询条件**: `redis_error OR mq_connection_failed OR es_timeout`

### 步骤4: 检查中间件服务状态
从日志中分析：
- 中间件服务是否正常运行
- 连接数是否正常
- 内存和CPU使用情况
- 队列长度或缓存命中率

## 常见原因分析

### Redis故障

#### 原因1: Redis内存不足
**特征**:
- 内存使用率接近100%
- 日志中有"OOM command not allowed"
- 键驱逐（eviction）频繁
- 缓存命中率下降

**处理方案**:
1. **立即处理**:
   - 清理不必要的数据
   - 调整maxmemory策略
   - 手动删除大key
   - 启用内存告警

2. **内存优化**:
   - 使用更高效的数据结构
   - 压缩存储数据
   - 设置过期时间
   - 使用LRU淘汰策略

3. **架构优化**:
   - Redis集群化
   - 读写分离
   - 使用持久化策略
   - 定期清理数据

#### 原因2: Redis连接数耗尽
**特征**:
- 应用无法连接Redis
- 日志中有"max number of clients reached"
- 连接数达到maxclients限制
- 新连接被拒绝

**处理方案**:
1. **立即恢复**:
   - 增加maxclients配置
   - 清理空闲连接
   - 重启Redis服务
   - 检查连接泄漏

2. **连接优化**:
   - 使用连接池
   - 及时关闭连接
   - 减少不必要的连接
   - 监控连接数

3. **架构优化**:
   - Redis集群
   - 读写分离
   - 连接池管理

#### 原因3: Redis持久化故障
**特征**:
- RDB或AOF备份失败
- 磁盘空间不足
- 持久化进程阻塞
- 数据丢失风险

**处理方案**:
1. **立即处理**:
   - 检查磁盘空间
   - 修复持久化配置
   - 手动触发备份
   - 检查文件权限

2. **持久化优化**:
   - 调整RDB和AOF策略
   - 使用更快的磁盘
   - 分离持久化和数据目录
   - 监控持久化状态

### MQ故障

#### 原因1: 消息队列积压
**特征**:
- 队列长度持续增长
- 消息消费速度跟不上生产速度
- 队列内存或磁盘使用率高
- 消息延迟增加

**处理方案**:
1. **立即处理**:
   - 增加消费者实例
   - 提高消费并发度
   - 临时跳过非关键消息
   - 清理过期消息

2. **消费优化**:
   - 优化消费逻辑
   - 批量消费消息
   - 异步处理
   - 增加重试次数

3. **架构优化**:
   - 增加队列分区
   - 使用多队列
   - 死信队列处理
   - 监控队列长度

#### 原因2: MQ连接失败
**特征**:
- 生产者或消费者无法连接
- 日志中有连接超时或拒绝
- 消息发送或接收失败
- 网络问题或服务宕机

**处理方案**:
1. **立即恢复**:
   - 检查MQ服务状态
   - 重启MQ服务
   - 检查网络连接
   - 验证认证配置

2. **连接优化**:
   - 使用连接池
   - 配置重试机制
   - 实现心跳检测
   - 连接超时设置

3. **高可用**:
   - MQ集群部署
   - 配置镜像队列
   - 故障自动转移
   - 多地域部署

### Elasticsearch故障

#### 原因1: ES集群健康状态异常
**特征**:
- 集群状态为Yellow或Red
- 分片未分配
- 索引不可写
- 查询失败

**处理方案**:
1. **立即处理**:
   - 检查集群状态
   - 重新分配分片
   - 重启异常节点
   - 检查磁盘空间

2. **集群恢复**:
   - 检查节点状态
   - 查看集群日志
   - 修复网络问题
   - 恢复分片

3. **集群优化**:
   - 调整分片策略
   - 配置副本数
   - 优化索引策略
   - 定期维护

#### 原因2: ES内存不足
**特征**:
- JVM内存使用率高
- 频繁GC
- 查询性能下降
- 集群不稳定

**处理方案**:
1. **立即处理**:
   - 清理缓存
   - 重启ES节点
   - 调整JVM堆内存
   - 限制查询并发

2. **内存优化**:
   - 优化查询语句
   - 使用filter代替query
   - 限制返回结果数量
   - 优化索引设置

3. **架构优化**:
   - 增加节点
   - 调整分片大小
   - 使用冷热架构
   - 定期清理旧索引

## 紧急处理措施

### 立即操作（5分钟内）
1. **确认故障**: 确定是哪个中间件出现问题
2. **启用降级**: 暂时绕过故障中间件
3. **重启服务**: 如果是服务宕机，立即重启
4. **通知团队**: 通知相关开发和运维团队

### 短期措施（30分钟内）
1. **恢复服务**: 恢复中间件正常运行
2. **数据验证**: 确认数据没有丢失
3. **监控验证**: 监控中间件指标恢复正常
4. **应用验证**: 验证应用功能正常

### 长期优化
1. **架构优化**: 中间件集群化和高可用
2. **监控完善**: 建立中间件监控体系
3. **容量规划**: 定期评估容量需求
4. **容灾演练**: 定期进行故障演练

## 中间件管理命令

### Redis管理
```bash
# 查看Redis信息
redis-cli INFO

# 查看内存使用
redis-cli INFO memory

# 查看客户端连接
redis-cli CLIENT LIST

# 查看键统计
redis-cli INFO keyspace

# 清空数据库
redis-cli FLUSHDB

# 查看慢查询
redis-cli SLOWLOG GET 10
```

### RabbitMQ管理
```bash
# 查看队列状态
rabbitmqctl list_queues name messages consumers

# 查看连接
rabbitmqctl list_connections

# 查看集群状态
rabbitmqctl cluster_status

# 查看节点状态
rabbitmqctl status
```

### Elasticsearch管理
```bash
# 查看集群健康
curl -X GET "localhost:9200/_cluster/health?pretty"

# 查看节点信息
curl -X GET "localhost:9200/_nodes/stats?pretty"

# 查看索引状态
curl -X GET "localhost:9200/_cat/indices?v"

# 查看分片分配
curl -X GET "localhost:9200/_cat/shards?v"
```

## 验证步骤
1. 确认中间件服务正常运行
2. 检查连接数恢复正常
3. 验证应用功能正常
4. 确认无新的错误日志
5. 持续监控30分钟确保稳定

## 预防措施
1. **监控告警**: 建立中间件性能监控
2. **容量规划**: 提前规划容量
3. **高可用**: 配置集群和故障转移
4. **定期维护**: 定期清理和优化
5. **备份策略**: 定期备份数据

## 相关告警
- `HighMemoryUsage`: 内存使用率过高
- `HighCPUUsage`: CPU使用率过高
- `ServiceUnavailable`: 服务不可用
- `SlowResponse`: 响应时间过长

## 联系方式
- **中间件团队**: middleware-team@company.com
- **运维团队**: ops-team@company.com
- **紧急电话**: 400-xxx-xxxx

## 参考文档
- [Redis运维手册](internal-docs/redis-operations.md)
- [RabbitMQ最佳实践](internal-docs/rabbitmq-best-practices.md)
- [Elasticsearch集群管理](internal-docs/elasticsearch-cluster-management.md)
