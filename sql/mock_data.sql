-- ==========================================================
-- 云平台智能客服系统 - 模拟数据初始化脚本
-- 依赖: schema.sql (先执行建表)
-- 说明: 为 3 个测试用户生成订单、实例、监控数据
-- ==========================================================

-- ----------------------------------------------------------
-- 1. 用户数据 (与 app/auth/models.py 中的 Mock 用户对齐)
--    密码统一为 cloud@2024，hash 由 bcrypt 生成
--    此处用占位符，实际部署时需替换为真实 bcrypt hash
-- ----------------------------------------------------------
TRUNCATE TABLE users;

INSERT INTO users (user_id, username, password_hash, display_name, role) VALUES
('user_1001', 'alice', '$2b$12$PLACEHOLDER_HASH_FOR_cloud@2024', 'Alice (产品经理)', 'user'),
('user_1002', 'bob',   '$2b$12$PLACEHOLDER_HASH_FOR_cloud@2024', 'Bob (运维工程师)',   'user'),
('user_1003', 'admin', '$2b$12$PLACEHOLDER_HASH_FOR_cloud@2024', 'Admin (管理员)',     'admin');

-- ----------------------------------------------------------
-- 2. 订单数据
-- ----------------------------------------------------------
TRUNCATE TABLE cloud_orders;

-- user_1001 (高净值客户，企业级实例)
INSERT INTO cloud_orders (order_id, user_id, product_name, billing_mode, amount, status, created_at) VALUES
('ORD-1001-001', 'user_1001', 'ecs.g8a.4xlarge',      '包年包月', 12500.00, 'Paid',     '2023-10-01 10:00:00'),
('ORD-1001-002', 'user_1001', 'rds.mysql.c1.large',    '包年包月',  3600.00, 'Paid',     '2023-10-05 14:30:00'),
('ORD-1001-003', 'user_1001', '共享带宽 100Mbps',       '按量付费',   150.50, 'Paid',     '2023-11-01 08:15:00');

-- user_1002 (个人开发者，轻量实例)
INSERT INTO cloud_orders (order_id, user_id, product_name, billing_mode, amount, status, created_at) VALUES
('ORD-1002-001', 'user_1002', 'ecs.c7.large',          '按量付费',    45.20, 'Paid',     '2023-11-15 09:00:00'),
('ORD-1002-002', 'user_1002', '云盘 ESSD PL0 40G',      '包年包月',   120.00, 'Paid',     '2023-11-15 09:05:00'),
('ORD-1002-003', 'user_1002', 'ecs.c7.large',          '按量付费',    12.80, 'Unpaid',   '2023-11-16 10:00:00');

-- ----------------------------------------------------------
-- 3. 实例数据
-- ----------------------------------------------------------
TRUNCATE TABLE cloud_instances;

INSERT INTO cloud_instances (instance_id, user_id, order_id, instance_type, region_id, zone_id, status, public_ip) VALUES
('i-bp1_user1001_ecs', 'user_1001', 'ORD-1001-001', 'ecs.g8a.4xlarge',   'cn-beijing',    'cn-beijing-k', 'Running', '47.100.1.1'),
('rm-bp1_user1001_rds','user_1001', 'ORD-1001-002', 'rds.mysql.c1.large', 'cn-beijing',    'cn-beijing-l', 'Running', NULL),
('i-bp1_user1002_ecs', 'user_1002', 'ORD-1002-001', 'ecs.c7.large',       'cn-hangzhou',   'cn-hangzhou-h','Stopped', '114.55.2.2');

-- ----------------------------------------------------------
-- 4. 实例监控指标 (近 7 天)
--    user_1001: 低负载 (CPU < 5%, 内存 < 20%) → 资源闲置
--    user_1002: 中高负载 (CPU ~40%, 内存 ~63%) → 资源正常
-- ----------------------------------------------------------
TRUNCATE TABLE instance_metrics_daily;

-- user_1001 的 ECS 实例 (资源闲置，FinOps 优化目标)
INSERT INTO instance_metrics_daily (instance_id, user_id, metric_date, avg_cpu_usage_percent, avg_memory_usage_percent, max_network_out_mbps) VALUES
('i-bp1_user1001_ecs', 'user_1001', DATE_SUB(CURDATE(), INTERVAL 6 DAY), 2.10, 18.50, 1.20),
('i-bp1_user1001_ecs', 'user_1001', DATE_SUB(CURDATE(), INTERVAL 5 DAY), 2.50, 19.10, 1.60),
('i-bp1_user1001_ecs', 'user_1001', DATE_SUB(CURDATE(), INTERVAL 4 DAY), 3.20, 20.40, 2.00),
('i-bp1_user1001_ecs', 'user_1001', DATE_SUB(CURDATE(), INTERVAL 3 DAY), 1.90, 17.90, 1.00),
('i-bp1_user1001_ecs', 'user_1001', DATE_SUB(CURDATE(), INTERVAL 2 DAY), 2.80, 18.20, 1.40),
('i-bp1_user1001_ecs', 'user_1001', DATE_SUB(CURDATE(), INTERVAL 1 DAY), 2.40, 19.00, 1.30),
('i-bp1_user1001_ecs', 'user_1001', CURDATE(),                           2.00, 18.70, 1.10);

-- user_1002 的 ECS 实例 (负载正常)
INSERT INTO instance_metrics_daily (instance_id, user_id, metric_date, avg_cpu_usage_percent, avg_memory_usage_percent, max_network_out_mbps) VALUES
('i-bp1_user1002_ecs', 'user_1002', DATE_SUB(CURDATE(), INTERVAL 6 DAY), 36.50, 62.10, 42.00),
('i-bp1_user1002_ecs', 'user_1002', DATE_SUB(CURDATE(), INTERVAL 5 DAY), 41.20, 65.00, 51.00),
('i-bp1_user1002_ecs', 'user_1002', DATE_SUB(CURDATE(), INTERVAL 4 DAY), 38.40, 63.50, 48.00),
('i-bp1_user1002_ecs', 'user_1002', DATE_SUB(CURDATE(), INTERVAL 3 DAY), 44.00, 67.30, 55.00),
('i-bp1_user1002_ecs', 'user_1002', DATE_SUB(CURDATE(), INTERVAL 2 DAY), 39.10, 60.80, 47.00),
('i-bp1_user1002_ecs', 'user_1002', DATE_SUB(CURDATE(), INTERVAL 1 DAY), 42.80, 64.20, 53.00),
('i-bp1_user1002_ecs', 'user_1002', CURDATE(),                           40.30, 61.90, 49.00);
