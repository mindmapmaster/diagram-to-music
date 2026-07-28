import os

# MiniMax 音乐生成 API
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cp-qg1lWPpYimwyOcvGKm5GkhS6vhPVFAZKFbEvUvEy3QvVt1btbUYUF49fnyBfr6pVQgQ3QhsLBm70z3FtJ4GJJ0Gs-mrxgf9ekxNq5wSvmWkEMZJ9J79bMhg")
MINIMAX_API_URL = "https://api.minimaxi.com/v1/music_generation"
MINIMAX_MODEL = "music-2.6"

# 智谱 AI 配置
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "d13f82b5de734bd6a288da3265a2fd85.FlBWkvIcIjotr0Ww")
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_MODEL = "glm-4v-flash"
