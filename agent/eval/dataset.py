"""RAG 评估数据集（黄金标准 QA pairs）。

每条数据包含：
- question: 用户问题
- ground_truth: 标准答案（基于 mock_data 文档人工整理）
- relevant_sources: 该问题应该检索到的文档来源
- expected_agent: 完整 LangGraph 应路由到的业务 Agent

数据覆盖 mock_data 下的 6 份文档，确保评估覆盖全部知识库。
"""
from __future__ import annotations


EVAL_DATASET = [
    # === ecs_network_security.md ===
    {
        "question": "什么是 VPC？它和子网是什么关系？",
        "ground_truth": (
            "VPC（Virtual Private Cloud，专有网络）是地域级别的逻辑隔离网络。"
            "VPC 下必须划分交换机（VSwitch），交换机是可用区级别的。"
            "同一 VPC 下不同可用区的交换机内网默认互通，跨 VPC 默认隔离，"
            "需要通过云企业网（CEN）实现路由打通。"
        ),
        "relevant_sources": ["ecs_network_security.md"],
        "expected_agent": "product_agent",
    },
    {
        "question": "弹性公网 IP EIP 能跨地域绑定吗？",
        "ground_truth": (
            "不能。EIP 是地域级资源，北京的 EIP 只能绑定给北京地域的 ECS，严禁跨地域绑定。"
            "EIP 只能绑定在专有网络类型的资源上，例如 ECS 的主弹性网卡或辅助弹性网卡。"
        ),
        "relevant_sources": ["ecs_network_security.md"],
        "expected_agent": "product_agent",
    },
    {
        "question": "一块弹性网卡最多能加入几个安全组？",
        "ground_truth": (
            "一块弹性网卡（ENI）最多可加入 5 个安全组。系统会取这些安全组规则的并集。"
            "安全组的生效粒度是弹性网卡（ENI），而不是直接作用于 ECS 实例。"
        ),
        "relevant_sources": ["ecs_network_security.md"],
        "expected_agent": "product_agent",
    },
    # === ecs_product_info.md ===
    {
        "question": "ecs.g8a.4xlarge 是什么类型的实例？基于什么处理器？",
        "ground_truth": (
            "ecs.g8a.4xlarge 是第八代企业级通用型实例，基于 AMD EPYC 9004 处理器（Genoa）。"
            "属于通用型实例规格族，适用于 Web 服务、中小型数据库等均衡场景。"
        ),
        "relevant_sources": ["ecs_product_info.md"],
        "expected_agent": "product_agent",
    },
    {
        "question": "ecs.c7.8xlarge 适合什么业务场景？",
        "ground_truth": (
            "ecs.c7.8xlarge 是第七代企业级计算型实例，基于 Intel 处理器，"
            "适合高并发 Web 应用、批量计算、高性能计算等 CPU 密集型场景。"
            "支持高网络带宽和高 PPS。"
        ),
        "relevant_sources": ["ecs_product_info.md"],
        "expected_agent": "product_agent",
    },
    # === ecs_troubleshooting_guide.md ===
    {
        "question": "ECS 实例无法远程连接，一般有哪些排查方向？",
        "ground_truth": (
            "ECS 无法远程连接的常见排查方向包括："
            "1) 检查实例状态是否为运行中；"
            "2) 检查安全组是否放行 SSH（22）或 RDP（3389）端口；"
            "3) 检查实例是否带宽超限或被限流；"
            "4) 检查密码或密钥是否正确；"
            "5) 检查系统内 SSH 服务是否正常运行。"
        ),
        "relevant_sources": ["ecs_troubleshooting_guide.md"],
        "expected_agent": "product_agent",
    },
    # === rds_product_info.md ===
    {
        "question": "RDS MySQL 高可用版的主备架构是怎么样的？",
        "ground_truth": (
            "RDS MySQL 高可用版采用一主一备的双节点架构，支持 30 秒内自动故障转移，"
            "保障 99.99% 可用性。主备节点通过同城容灾实现数据同步。"
        ),
        "relevant_sources": ["rds_product_info.md"],
        "expected_agent": "product_agent",
    },
    # === billing_and_refund_policy.md ===
    {
        "question": "五天无理由退款有什么限制条件？",
        "ground_truth": (
            "五天无理由退款的限制条件包括："
            "1) 仅针对新购的包年包月实例；"
            "2) 自购买之日起 5 天内可申请；"
            "3) 每个用户每年有退款次数限制；"
            "4) 退款前不能有违规行为；"
            "5) 部分促销活动实例不支持五天无理由退款。"
        ),
        "relevant_sources": ["billing_and_refund_policy.md"],
        "expected_agent": "product_agent",
    },
    {
        "question": "按量付费和包年包月有什么区别？",
        "ground_truth": (
            "按量付费是后付费模式，按实际使用时长计费，单价较高，灵活性强，适合短期测试；"
            "包年包月是预付费模式，单价较低，享受折扣，适合长期稳定业务。"
            "按量付费实例可随时释放，包年包月到期后才会自动释放。"
        ),
        "relevant_sources": ["billing_and_refund_policy.md"],
        "expected_agent": "product_agent",
    },
    # === ticket_and_support_guide.md ===
    {
        "question": "提交工单时如何选择工单类型？",
        "ground_truth": (
            "提交工单时应根据问题性质选择类型："
            "产品咨询选售前咨询；"
            "使用问题选售后技术支持；"
            "账单问题选财务类工单；"
            "备案问题选备案类工单。"
            "选择正确的工单类型能加快响应速度。"
        ),
        "relevant_sources": ["ticket_and_support_guide.md"],
        "expected_agent": "product_agent",
    },
    # === 跨文档综合题 ===
    {
        "question": "我要在高可用架构下部署 Java Web 服务 + MySQL，应该怎么选 ECS 实例和 RDS？",
        "ground_truth": (
            "建议选择计算型实例 ecs.c7.8xlarge（32核64G）承载 Java Web 服务，"
            "搭配 RDS MySQL 高可用版（一主一备、30秒故障转移）。"
            "网络层应划分 VPC 并在不同可用区部署交换机实现同城容灾，"
            "安全组上 Web 集群开放 80/443 入向，数据库安全组仅允许 Web 安全组内网访问 3306。"
        ),
        "relevant_sources": ["ecs_product_info.md", "rds_product_info.md", "ecs_network_security.md"],
        "expected_agent": "recommendation_agent",
    },
]


def get_dataset() -> list[dict]:
    """返回完整评估数据集。"""
    return EVAL_DATASET.copy()
