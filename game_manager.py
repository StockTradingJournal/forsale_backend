import random
import string
from typing import Dict, List, Optional, Any
from enum import Enum

class GamePhase(Enum):
    LOBBY = "lobby"
    PHASE1_BIDDING = "phase1_bidding"
    PHASE2_SELLING = "phase2_selling"
    GAME_OVER = "game_over"

class Player:
    def __init__(self, sid: str, nickname: str):
        self.sid = sid
        self.nickname = nickname
        self.ready = False
        self.coins = 18000  # Starting coins
        self.properties = []  # Property cards owned
        self.cheques = []  # Money cheques earned
        self.current_bid = 0
        self.has_passed = False

class Room:
    def __init__(self, room_id: str, creator_sid: str, creator_nickname: str):
        self.room_id = room_id
        self.players: Dict[str, Player] = {}
        self.phase = GamePhase.LOBBY
        self.property_deck = list(range(1, 31))  # Cards 1-30
        self.cheque_deck = [0, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000, 15000]
        self.current_properties = []  # Properties on table
        self.current_cheques = []  # Cheques on table
        self.current_bid = 0
        self.current_high_bidder = None
        self.turn_order = []
        self.current_turn_index = 0
        self.round_number = 1
        
        # Add creator as first player
        creator = Player(creator_sid, creator_nickname)
        self.players[creator_sid] = creator
        
        # Shuffle decks
        random.shuffle(self.property_deck)
        random.shuffle(self.cheque_deck)

class GameManager:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.player_to_room: Dict[str, str] = {}

    def _generate_room_id(self) -> str:
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    async def create_room(self, sid: str, nickname: str) -> str:
        room_id = self._generate_room_id()
        while room_id in self.rooms:
            room_id = self._generate_room_id()
        
        room = Room(room_id, sid, nickname)
        self.rooms[room_id] = room
        self.player_to_room[sid] = room_id
        
        return room_id

    async def join_room(self, sid: str, room_id: str, nickname: str) -> bool:
        if room_id not in self.rooms:
            return False
        
        room = self.rooms[room_id]
        
        if len(room.players) >= 6:
            return False
        
        if room.phase != GamePhase.LOBBY:
            return False
        
        player = Player(sid, nickname)
        room.players[sid] = player
        self.player_to_room[sid] = room_id
        
        return True

    async def set_player_ready(self, sid: str, ready: bool) -> Optional[str]:
        room_id = self.player_to_room.get(sid)
        if not room_id or room_id not in self.rooms:
            return None
        
        room = self.rooms[room_id]
        if sid in room.players:
            room.players[sid].ready = ready
        
        return room_id

    async def start_game(self, sid: str) -> Optional[str]:
        room_id = self.player_to_room.get(sid)
        if not room_id or room_id not in self.rooms:
            return None
        
        room = self.rooms[room_id]
        
        # 3명 이상 필요
        if len(room.players) < 3:
            return None
        
        # 호스트만 시작 가능 (첫 번째 플레이어)
        first_player_sid = next(iter(room.players.keys())) if room.players else None
        if sid != first_player_sid:
            return None
        
        # 호스트를 제외한 모든 플레이어가 준비 완료되어야 함
        non_host_players = [p for p_sid, p in room.players.items() if p_sid != first_player_sid]
        if not all(p.ready for p in non_host_players):
            return None
        
        await self._start_phase1(room)
        return room_id

    async def _start_phase1(self, room: Room):
        room.phase = GamePhase.PHASE1_BIDDING
        # Only shuffle turn order if not already set (first round)
        if not room.turn_order:
            room.turn_order = list(room.players.keys())
            random.shuffle(room.turn_order)
        room.current_turn_index = 0
        
        # Deal properties equal to number of players
        num_players = len(room.players)
        room.current_properties = sorted(room.property_deck[:num_players])
        room.property_deck = room.property_deck[num_players:]
        
        # Reset bidding state
        room.current_bid = 0
        room.current_high_bidder = None
        for player in room.players.values():
            player.current_bid = 0
            player.has_passed = False

    async def handle_bid(self, sid: str, amount: int) -> Optional[str]:
        room_id = self.player_to_room.get(sid)
        if not room_id or room_id not in self.rooms:
            return None
        
        room = self.rooms[room_id]
        
        if room.phase != GamePhase.PHASE1_BIDDING:
            return None
        
        if room.turn_order[room.current_turn_index] != sid:
            return None
        
        player = room.players[sid]
        
        if player.has_passed:
            return None
        
        if amount <= room.current_bid:
            return None
        
        if amount > player.coins:
            return None
        
        # Valid bid
        player.current_bid = amount
        room.current_bid = amount
        room.current_high_bidder = sid
        
        # Move to next active player
        await self._next_turn(room)
        
        return room_id

    async def handle_pass(self, sid: str) -> Optional[str]:
        room_id = self.player_to_room.get(sid)
        if not room_id or room_id not in self.rooms:
            return None
        
        room = self.rooms[room_id]
        
        if room.phase != GamePhase.PHASE1_BIDDING:
            return None
        
        if room.turn_order[room.current_turn_index] != sid:
            return None
        
        player = room.players[sid]
        
        if player.has_passed:
            return None
        
        # Player passes - takes lowest property and pays penalty based on current bid
        player.has_passed = True
        lowest_property = min(room.current_properties)
        room.current_properties.remove(lowest_property)
        player.properties.append(lowest_property)
        
        # Calculate penalty: if no previous bid, penalty is 0. Otherwise, floor(currentBid / 2 / 500) * 500
        if player.current_bid == 0:
            penalty = 0
        else:
            penalty = (player.current_bid // 2 // 500) * 500
        
        player.coins -= penalty
        player.current_bid = 0
        
        # Check if only one player remains
        active_players = [p for p in room.players.values() if not p.has_passed]
        
        if len(active_players) == 1:
            # Last player gets highest property and pays full bid
            last_player = active_players[0]
            highest_property = max(room.current_properties)
            room.current_properties.remove(highest_property)
            last_player.properties.append(highest_property)
            last_player.coins -= last_player.current_bid
            last_player.current_bid = 0
            
            # End of round
            await self._end_phase1_round(room)
        else:
            # Continue with next player
            await self._next_turn(room)
        
        return room_id

    async def _next_turn(self, room: Room):
        # Find next active player
        attempts = 0
        while attempts < len(room.turn_order):
            room.current_turn_index = (room.current_turn_index + 1) % len(room.turn_order)
            current_player_sid = room.turn_order[room.current_turn_index]
            
            if not room.players[current_player_sid].has_passed:
                break
            
            attempts += 1

    async def _end_phase1_round(self, room: Room):
        # Check if more rounds needed
        if len(room.property_deck) >= len(room.players):
            # Start next round
            room.round_number += 1
            await self._start_phase1(room)
        else:
            # Move to Phase 2
            await self._start_phase2(room)

    async def _start_phase2(self, room: Room):
        room.phase = GamePhase.PHASE2_SELLING
        # Deal cheques equal to number of players
        num_players = len(room.players)
        room.current_cheques = sorted(room.cheque_deck[:num_players], reverse=True)
        room.cheque_deck = room.cheque_deck[num_players:]
        
        # Reset for card selection
        for player in room.players.values():
            player.current_bid = 0  # Reuse for selected card

    async def handle_play_card(self, sid: str, card_id: int) -> Optional[str]:
        room_id = self.player_to_room.get(sid)
        if not room_id or room_id not in self.rooms:
            return None
        
        room = self.rooms[room_id]
        
        if room.phase != GamePhase.PHASE2_SELLING:
            return None
        
        player = room.players[sid]
        
        if card_id not in player.properties:
            return None
        
        if player.current_bid != 0:  # Already selected a card
            return None
        
        player.current_bid = card_id  # Store selected card
        
        # Check if all players have selected
        if all(p.current_bid != 0 for p in room.players.values()):
            await self._resolve_phase2(room)
        
        return room_id

    async def _resolve_phase2(self, room: Room):
        # Sort players by selected card value (descending)
        player_cards = [(sid, player.current_bid) for sid, player in room.players.items()]
        player_cards.sort(key=lambda x: x[1], reverse=True)
        
        # Distribute cheques
        for i, (sid, card_value) in enumerate(player_cards):
            player = room.players[sid]
            player.properties.remove(card_value)
            player.cheques.append(room.current_cheques[i])
            player.current_bid = 0
        
        # Check if game over or continue
        if any(len(p.properties) > 0 for p in room.players.values()):
            await self._start_phase2(room)
        else:
            room.phase = GamePhase.GAME_OVER

    async def handle_disconnect(self, sid: str, sio):
        room_id = self.player_to_room.get(sid)
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            
            # 호스트가 나가는 경우 (첫 번째 플레이어)
            first_player_sid = next(iter(room.players.keys())) if room.players else None
            is_host_leaving = sid == first_player_sid
            
            if sid in room.players:
                del room.players[sid]
            
            if len(room.players) == 0 or is_host_leaving:
                # 방 파괴 - 모든 플레이어에게 알림
                await sio.emit('room:destroyed', {'message': '호스트가 나가서 방이 파괴되었습니다.'}, room=room_id)
                del self.rooms[room_id]
            else:
                await self.broadcast_state(room_id, sio)
        
        if sid in self.player_to_room:
            del self.player_to_room[sid]

    async def broadcast_state(self, room_id: str, sio):
        if room_id not in self.rooms:
            return
        
        room = self.rooms[room_id]
        
        # Get first player (creator) as host
        first_player_sid = next(iter(room.players.keys())) if room.players else None
        
        # Create player list with frontend expected format
        players_list = []
        for i, (sid, p) in enumerate(room.players.items()):
            players_list.append({
                'id': sid,
                'nickname': p.nickname,
                'avatar': f'👤',  # Default avatar
                'isReady': p.ready,
                'isHost': sid == first_player_sid,
                'coins': p.coins,
                'propertyCount': len(p.properties),
                'chequeCount': len(p.cheques),
                'currentBid': p.current_bid,
                'hasPassed': p.has_passed,
                'isCurrentTurn': room.turn_order and len(room.turn_order) > room.current_turn_index and room.turn_order[room.current_turn_index] == sid
            })
        
        # Create state object
        state = {
            'roomId': room_id,
            'gameState': 'lobby' if room.phase == GamePhase.LOBBY else 'playing',
            'phase': room.phase.value,
            'players': players_list,
            'currentProperties': room.current_properties,
            'currentCheques': room.current_cheques,
            'currentBid': room.current_bid,
            'currentHighBidder': room.current_high_bidder,
            'currentTurn': room.turn_order[room.current_turn_index] if room.turn_order and len(room.turn_order) > room.current_turn_index else None,
            'roundNumber': room.round_number
        }
        
        # Send to all players in room
        await sio.emit('room:state', state, room=room_id)