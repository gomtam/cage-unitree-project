import os
from pathlib import Path
from dotenv import load_dotenv

# 현재 파일의 부모 디렉터리 (프로젝트 루트) 구하기
PROJECT_ROOT = Path(__file__).parent.parent
ENV_PATH = PROJECT_ROOT / '.env'

# 절대 경로로 .env 파일 로드
load_dotenv(dotenv_path=str(ENV_PATH))

SERIAL_NUMBER = os.getenv("SERIAL_NUMBER")
UNITREE_USERNAME = os.getenv("UNITREE_USERNAME")
UNITREE_PASSWORD = os.getenv("UNITREE_PASSWORD")