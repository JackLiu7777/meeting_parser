import os
from dotenv import load_dotenv

load_dotenv()

# 默认使用智谱 GLM-4-Flash（免费、国内直连、OpenAI 兼容接口）。
# 申请免费 API Key：https://open.bigmodel.cn/  → 注册 → 控制台 → API Keys
# 也可换成任何 OpenAI 兼容接口（DeepSeek / 通义千问 / Moonshot / OpenAI 等），
# 只需在 .env 里覆盖下面三个变量即可。
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4-flash")
