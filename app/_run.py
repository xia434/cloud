"""临时启动脚本，强制日志输出到文件+控制台，用完即删。"""
import sys, os, logging

# 配置 logging 同时输出到文件和控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(r'D:\deep_research\deep_research\cloud_agent\app\uvicorn.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)

# 把 agent 目录加入 sys.path
AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agent')
sys.path.insert(0, AGENT_DIR)

print('>>> 启动 uvicorn...', flush=True)
import uvicorn
print('>>> uvicorn imported, starting server...', flush=True)
uvicorn.run(
    'app_main:app',
    host='0.0.0.0',
    port=5000,
    log_level='info',
    timeout_keep_alive=30,
)
