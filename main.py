import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from game_manager import GameManager
import uvicorn

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=["*"]
)

# Create FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create game manager
game_manager = GameManager()
game_manager.set_sio(sio)

# Combine FastAPI and Socket.IO
socket_app = socketio.ASGIApp(sio, app)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    await game_manager.handle_disconnect(sid, sio)

@sio.event
async def create_room(sid, data):
    try:
        nickname = data.get('nickname')
        if not nickname:
            await sio.emit('room:error', {'code': 'INVALID_DATA', 'message': 'Nickname required'}, room=sid)
            return
        
        room_id = await game_manager.create_room(sid, nickname)
        await sio.enter_room(sid, room_id)
        await sio.emit('room:created', {'roomId': room_id}, room=sid)
        await game_manager.broadcast_state(room_id, sio)
    except Exception as e:
        await sio.emit('room:error', {'code': 'CREATE_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def join_room(sid, data):
    try:
        print(f"Client {sid}, data {data} attempting to join room")
        room_id = data.get('roomId')
        nickname = data.get('nickname')
        
        if not room_id or not nickname:
            await sio.emit('room:error', {'code': 'INVALID_DATA', 'message': 'Room ID and nickname required'}, room=sid)
            return
        
        success = await game_manager.join_room(sid, room_id, nickname)
        print(f"Client {sid}, success {success}")
        if success:
            await sio.enter_room(sid, room_id)
            await sio.emit('room:joined', {'roomId': room_id}, room=sid)
            await game_manager.broadcast_state(room_id, sio)
        else:
            await sio.emit('room:error', {'code': 'JOIN_FAILED', 'message': 'Could not join room'}, room=sid)
        print("join done")
    except Exception as e:
        await sio.emit('room:error', {'code': 'JOIN_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def player_ready(sid, data):
    try:
        ready = data.get('ready', False)
        room_id = await game_manager.set_player_ready(sid, ready)
        if room_id:
            await game_manager.broadcast_state(room_id, sio)
    except Exception as e:
        await sio.emit('room:error', {'code': 'READY_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def start_game(sid, data):
    try:
        room_id = await game_manager.start_game(sid)
        if room_id:
            await game_manager.broadcast_state(room_id, sio)
        else:
            await sio.emit('room:error', {'code': 'START_FAILED', 'message': '게임을 시작할 수 없습니다. 3명 이상 참여, 모든 일반 플레이어 준비 완료 필요'}, room=sid)
    except Exception as e:
        await sio.emit('room:error', {'code': 'START_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def place_bid(sid, data):
    try:
        amount = data.get('amount')
        if amount is None:
            await sio.emit('room:error', {'code': 'INVALID_BID', 'message': 'Bid amount required'}, room=sid)
            return
        
        room_id = await game_manager.handle_bid(sid, amount)
        if room_id:
            await game_manager.broadcast_state(room_id, sio)
    except Exception as e:
        await sio.emit('room:error', {'code': 'BID_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def pass_turn(sid, data):
    try:
        room_id = await game_manager.handle_pass(sid)
        if room_id:
            await game_manager.broadcast_state(room_id, sio)
    except Exception as e:
        await sio.emit('room:error', {'code': 'PASS_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def leave_room(sid, data):
    try:
        # 소켓 룸에서 먼저 제거
        room_id = game_manager.player_to_room.get(sid)
        if room_id:
            await sio.leave_room(sid, room_id)
        
        await game_manager.handle_disconnect(sid, sio)
    except Exception as e:
        await sio.emit('room:error', {'code': 'LEAVE_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def play_card(sid, data):
    try:
        card_id = data.get('card_id')
        if card_id is None:
            await sio.emit('room:error', {'code': 'INVALID_CARD', 'message': 'Card ID required'}, room=sid)
            return
        
        room_id = await game_manager.handle_play_card(sid, card_id)
        if room_id:
            await game_manager.broadcast_state(room_id, sio)
    except Exception as e:
        await sio.emit('room:error', {'code': 'PLAY_FAILED', 'message': str(e)}, room=sid)

@sio.event
async def chat_message(sid, data):
    try:
        message = data.get('message')
        if not message:
            return
        
        room_id = game_manager.player_to_room.get(sid)
        if not room_id or room_id not in game_manager.rooms:
            return
        
        room = game_manager.rooms[room_id]
        player = room.players.get(sid)
        if not player:
            return
        
        # Broadcast chat message to all players in room
        import time
        chat_data = {
            'playerId': sid,
            'nickname': player.nickname,
            'message': message,
            'timestamp': int(time.time() * 1000)
        }
        await sio.emit('chat:message', chat_data, room=room_id)
    except Exception as e:
        print(f"Chat message error: {e}")

if __name__ == "__main__":
    uvicorn.run(socket_app, host="0.0.0.0", port=8000)