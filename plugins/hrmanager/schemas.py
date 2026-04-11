from pydantic import BaseModel, Field
from typing import Optional


class SiteHRConfig(BaseModel):
    """
    站点HR配置数据模型
    """
    # 站点名称
    site_name: str = Field(..., description="站点名称，用于标识适用于哪个站点")
    # H&R时间（小时）
    time: float = Field(default=0.0, description="H&R时间（小时），站点默认的H&R时间，做种时间达到H&R时间后移除标签")
    # 附加做种时间（小时）
    additional_seed_time: Optional[float] = Field(default=None, description="附加做种时间（小时），在H&R时间上额外增加的做种时长")
    # 分享率
    hr_ratio: float = Field(default=0.0, description="分享率，做种时期望达到的分享比例，达到目标分享率后移除标签")
    # H&R激活
    hr_active: bool = Field(default=False, description="H&R激活，站点是否已启用全站H&R，开启后所有种子均视为H&R种子")
    # H&R满足要求的期限（天数）
    hr_deadline_days: int = Field(default=0, description="H&R满足要求的期限（天数），需在此天数内满足H&R要求")

    # 告警级别（只读扩展字段）
    alert_level: Optional[str] = Field(default=None, description="告警级别：normal/warning/urgent/timeout")
    # 优先级分数（只读扩展字段）
    priority_score: Optional[float] = Field(default=None, description="优先级分数，越高越紧急")


class HRManagerConfig(BaseModel):
    """
    HR管理插件配置数据模型
    """
    # 是否启用插件
    enabled: bool = Field(default=False, description="是否启用插件")
    # HR标签
    hr_tag: str = Field(default="HR", description="用于标记HR种子的标签")
    # 出种标签
    finished_tag: str = Field(default="已完成", description="种子满足HR条件后使用的标签")
    # 检查间隔（秒）
    check_interval: int = Field(default=3600, description="检查HR种子条件的时间间隔（秒）")
    # 站点HR配置列表
    sites_config: list[SiteHRConfig] = Field(default_factory=list, description="各站点的HR标准配置列表")
    # 监控下载器
    monitor_downloaders: list[str] = Field(default_factory=list, description="需要监控的下载器名称列表，空表示监控全部")
