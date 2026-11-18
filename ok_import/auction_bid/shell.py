"""自动拍卖插件入口: 转发到 src/tasks 里的完整实现。

实现文件留在主仓库 (src/tasks/AutoBidAuctionTask.py 与 src/tasks/auction/),
本插件只负责让任务出现在任务列表, 不含业务逻辑。
"""

from src.tasks.AutoBidAuctionTask import AutoBidAuctionTask  # noqa: F401
