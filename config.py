import os

# MiniMax 音乐生成 API
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_API_URL = "https://api.minimaxi.com/v1/music_generation"
MINIMAX_MODEL = "music-2.6"

# 智谱 AI 配置
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_MODEL = "glm-4v-flash"
