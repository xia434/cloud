-- ==========================================================
-- 云平台智能客服系统 - 数据库建表脚本
-- 数据库: cloud_platform
-- 引擎: InnoDB, 字符集: utf8mb4
-- ==========================================================

-- ----------------------------------------------------------
-- 1. 用户表 (app/auth/models.py 当前为内存 Mock，生产环境用此表)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    user_id VARCHAR(50) NOT NULL UNIQUE COMMENT '用户唯一标识 (如 user_1001)',
    username VARCHAR(50) NOT NULL UNIQUE COMMENT '登录用户名',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希 (bcrypt)',
    display_name VARCHAR(100) NOT NULL COMMENT '显示名称',
    role VARCHAR(20) NOT NULL DEFAULT 'user' COMMENT '角色 (user / admin)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户认证表';

-- ----------------------------------------------------------
-- 2. 云产品订单表 (MCP Server: query_user_orders)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS cloud_orders (
    order_id VARCHAR(50) PRIMARY KEY COMMENT '订单唯一ID',
    user_id VARCHAR(50) NOT NULL COMMENT '用户ID',
    product_name VARCHAR(100) NOT NULL COMMENT '产品名称 (如: ecs.g8a.xlarge)',
    billing_mode VARCHAR(20) NOT NULL COMMENT '计费模式 (包年包月, 按量付费)',
    amount DECIMAL(10, 2) NOT NULL COMMENT '订单金额',
    status VARCHAR(20) NOT NULL COMMENT '订单状态 (Paid, Unpaid, Refunded)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='云产品订单表';

-- ----------------------------------------------------------
-- 3. 云资源实例表 (MCP Server: query_user_instances)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS cloud_instances (
    instance_id VARCHAR(50) PRIMARY KEY COMMENT '实例唯一ID',
    user_id VARCHAR(50) NOT NULL COMMENT '所属用户',
    order_id VARCHAR(50) NOT NULL COMMENT '关联的购买订单',
    instance_type VARCHAR(100) NOT NULL COMMENT '实例规格',
    region_id VARCHAR(50) NOT NULL COMMENT '所在地域',
    zone_id VARCHAR(50) NOT NULL COMMENT '所在可用区',
    status VARCHAR(20) NOT NULL COMMENT '实例运行状态 (Running, Stopped)',
    public_ip VARCHAR(20) COMMENT '公网 IP',
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='云资源实例表';

-- ----------------------------------------------------------
-- 4. 实例日级监控指标表 (MCP Server: analyze_instance_usage)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS instance_metrics_daily (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    instance_id VARCHAR(50) NOT NULL COMMENT '实例ID',
    user_id VARCHAR(50) NOT NULL COMMENT '所属用户ID',
    metric_date DATE NOT NULL COMMENT '统计日期',
    avg_cpu_usage_percent DECIMAL(5,2) NOT NULL COMMENT '当日平均CPU利用率',
    avg_memory_usage_percent DECIMAL(5,2) NOT NULL COMMENT '当日平均内存利用率',
    max_network_out_mbps DECIMAL(8,2) NOT NULL COMMENT '当日出口带宽峰值(Mbps)',
    INDEX idx_instance_date (instance_id, metric_date),
    INDEX idx_user_instance (user_id, instance_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实例日级监控指标表';
