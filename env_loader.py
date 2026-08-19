"""
로컬 실행용 .env 로더 (외부 의존성 없음)

프로젝트 루트의 .env 파일을 읽어 os.environ에 채워넣는다.
- 이미 설정된 환경변수는 덮어쓰지 않는다 (실제 환경변수 우선)
- 형식: KEY=VALUE (한 줄에 하나), '#'로 시작하는 줄과 빈 줄은 무시
- 값 양쪽의 따옴표(" 또는 ')는 제거
- .env 파일이 없으면 조용히 넘어감 (배포 환경에서는 실제 환경변수를 씀)

사용: 각 진입점(bot.py, screening.py 등) 최상단에서
    from env_loader import load_env
    load_env()
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env(path: str = None) -> None:
    if path is None:
        path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # 양쪽 따옴표 제거
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                # 이미 실제 환경변수로 설정돼 있으면 덮어쓰지 않음
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"[env_loader] .env 로드 실패 (무시하고 계속) — {e}")
