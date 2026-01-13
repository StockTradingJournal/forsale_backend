# ForSale 게임 서버

ForSale 보드게임의 백엔드 서버입니다.

## 🚀 빠른 시작

### macOS/Linux 사용자

1. **환경 설정 (최초 1회만)**
   ```bash
   ./setup.sh
   ```

2. **서버 실행**
   ```bash
   ./start.sh
   ```

### Windows 사용자

1. **환경 설정 (최초 1회만)**
   ```cmd
   setup.bat
   ```

2. **서버 실행**
   ```cmd
   start.bat
   ```

## 📋 수동 실행 방법

환경 설정:
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate.bat
pip install -r requirements.txt
```

서버 실행:
```bash
source venv/bin/activate  # Windows: venv\Scripts\activate.bat
uvicorn main:socket_app --reload --host 0.0.0.0 --port 8000
```

## 🌐 접속 정보

- **서버 주소**: http://localhost:8000
- **API 문서**: http://localhost:8000/docs
- **WebSocket**: ws://localhost:8000/ws/{room_id}

## 📁 파일 구조

```
forsale_server/
├── main.py           # FastAPI 서버 메인 파일
├── game_manager.py   # 게임 로직 관리
├── requirements.txt  # Python 의존성
├── setup.sh         # 환경 설정 스크립트 (macOS/Linux)
├── start.sh         # 서버 실행 스크립트 (macOS/Linux)
├── setup.bat        # 환경 설정 스크립트 (Windows)
├── start.bat        # 서버 실행 스크립트 (Windows)
└── README.md        # 이 파일
```

## 🛠 개발 환경

- Python 3.7+
- FastAPI
- WebSocket 지원