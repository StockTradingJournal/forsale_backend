import random
import string
import asyncio
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
        self.selected_property = None  # For Phase 2 - property card selected for this round

class Room:
    def __init__(self, room_id: str, creator_sid: str, creator_nickname: str):
        self.room_id = room_id
        self.players: Dict[str, Player] = {}
        self.phase = GamePhase.LOBBY
        self.property_deck = list(range(1, 31))  # Cards 1-30
        self.cheque_deck = [0, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 15000]  # No 1000 and 14000
        self.current_properties = []  # Properties on table
        self.current_cheques = []  # Cheques on table
        self.current_bid = 0
        self.current_high_bidder = None
        self.turn_order = []
        self.current_turn_index = 0
        self.round_number = 1
        self.turn_timer_task = None  # Asyncio task for turn timer
        self.turn_timeout = 30  # 30 seconds per turn
        self.phase2_selections = {}  # Track Phase 2 card selections {player_sid: card_value}
        self.phase2_round_number = 1  # Track Phase 2 round separately
        self.last_round_winner = None  # Track winner of last round to determine next round's starting player
        
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
        self.sio = None  # Will be set by main.py

    def set_sio(self, sio):
        """Set the socket.io instance for broadcasting"""
        self.sio = sio

    async def _start_turn_timer(self, room: Room):
        """Start a timer for the current player's turn"""
        # Cancel existing timer if any
        if room.turn_timer_task:
            room.turn_timer_task.cancel()
        
        # Verify current player hasn't passed
        if room.turn_order and room.current_turn_index < len(room.turn_order):
            current_player_sid = room.turn_order[room.current_turn_index]
            player = room.players.get(current_player_sid)
            
            if player and player.has_passed:
                print(f"⚠️ Warning: Trying to start timer for {player.nickname} who already passed!")
                # Force move to next turn
                has_active = await self._next_turn(room)
                if has_active:
                    print(f"✓ Moved to next active player")
                    if self.sio:
                        await self.broadcast_state(room.room_id, self.sio)
                    # Restart timer for the correct player
                    await self._start_turn_timer(room)
                    return
                else:
                    print(f"⚠️ No active players found, ending round")
                    await self._end_phase1_round(room)
                    if self.sio:
                        await self.broadcast_state(room.room_id, self.sio)
                    return
        
        # Create new timer task
        async def timer_expired():
            try:
                await asyncio.sleep(room.turn_timeout)
                # Time's up - auto pass for current player
                if room.phase == GamePhase.PHASE1_BIDDING:
                    current_player_sid = room.turn_order[room.current_turn_index]
                    player = room.players.get(current_player_sid)
                    
                    if player:
                        if not player.has_passed:
                            print(f"⏰ Timer expired for player {player.nickname}, auto-passing")
                            await self.handle_pass(current_player_sid)
                            if self.sio:
                                await self.broadcast_state(room.room_id, self.sio)
                        else:
                            # Player has already passed but is still current turn - force next turn
                            print(f"⚠️ Timer expired but player {player.nickname} already passed, forcing next turn")
                            has_active = await self._next_turn(room)
                            
                            if has_active:
                                # Found next active player, restart timer
                                await self._start_turn_timer(room)
                                if self.sio:
                                    await self.broadcast_state(room.room_id, self.sio)
                            else:
                                # No active players, end round
                                print("⚠️ No active players found, ending round")
                                self._cancel_turn_timer(room)
                                await self._end_phase1_round(room)
                                if self.sio:
                                    await self.broadcast_state(room.room_id, self.sio)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Error in timer_expired: {e}")
        
        room.turn_timer_task = asyncio.create_task(timer_expired())

    def _cancel_turn_timer(self, room: Room):
        """Cancel the current turn timer"""
        if room.turn_timer_task:
            room.turn_timer_task.cancel()
            room.turn_timer_task = None

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
        print(f"▶️ Starting Phase 1 round {room.round_number}")
        room.phase = GamePhase.PHASE1_BIDDING
        # Only shuffle turn order if not already set (first round)
        if not room.turn_order:
            room.turn_order = list(room.players.keys())
            random.shuffle(room.turn_order)
            print(f"🔀 Initial turn order: {[room.players[sid].nickname for sid in room.turn_order]}")
        elif room.last_round_winner and room.last_round_winner in room.turn_order:
            # Reorder turn_order to start with last round's winner
            winner_index = room.turn_order.index(room.last_round_winner)
            room.turn_order = room.turn_order[winner_index:] + room.turn_order[:winner_index]
            print(f"🔀 Reordered turn order (winner starts): {[room.players[sid].nickname for sid in room.turn_order]}")
        
        room.current_turn_index = 0
        
        # Deal properties equal to number of players
        num_players = len(room.players)
        room.current_properties = sorted(room.property_deck[:num_players])
        room.property_deck = room.property_deck[num_players:]
        print(f"🏠 Dealt properties: {room.current_properties}")
        print(f"📦 Properties remaining in deck: {len(room.property_deck)}")
        
        # Reset bidding state
        room.current_bid = 0
        room.current_high_bidder = None
        for player in room.players.values():
            player.current_bid = 0
            player.has_passed = False
        print(f"✅ Reset all players: has_passed=False, current_bid=0")
        
        # Start turn timer for first player
        first_player = room.players[room.turn_order[0]]
        print(f"⏰ Starting turn timer for {first_player.nickname}")
        await self._start_turn_timer(room)

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
        
        print(f"💰 {player.nickname} bid {amount}")
        
        # Check if only one player remains (all others have passed)
        active_players = [p for p in room.players.values() if not p.has_passed]
        print(f"📊 Active players remaining: {len(active_players)}/{len(room.players)}")
        for p in room.players.values():
            print(f"  - {p.nickname}: has_passed={p.has_passed}, current_bid={p.current_bid}")
        
        if len(active_players) == 1:
            # Last player gets highest property and pays full bid
            last_player = active_players[0]
            
            # Safety check: ensure there are properties available
            if not room.current_properties:
                print(f"⚠️ ERROR: No properties available for last player {last_player.nickname}!")
                self._cancel_turn_timer(room)
                await self._end_phase1_round(room)
                return room_id
            
            highest_property = max(room.current_properties)
            room.current_properties.remove(highest_property)
            last_player.properties.append(highest_property)
            bid_paid = last_player.current_bid
            last_player.coins -= last_player.current_bid
            last_player.current_bid = 0
            
            print(f"🏆 {last_player.nickname} wins the round! Got property {highest_property}, paid {bid_paid}")
            
            # Store the winner of this round
            for player_sid, p in room.players.items():
                if p == last_player:
                    room.last_round_winner = player_sid
                    break
            
            # Cancel timer - round is over
            self._cancel_turn_timer(room)
            
            # End of round
            await self._end_phase1_round(room)
        else:
            # Move to next active player
            has_active = await self._next_turn(room)
            
            if has_active:
                # Restart timer for next player
                await self._start_turn_timer(room)
            else:
                # No active players left (shouldn't happen in normal flow, but handle it)
                print("⚠️ Warning: No active players found after bid, ending round")
                self._cancel_turn_timer(room)
                await self._end_phase1_round(room)
        
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
        
        # Safety check: ensure there are properties available
        if not room.current_properties:
            print(f"⚠️ ERROR: No properties available when {player.nickname} tried to pass!")
            return None
        
        lowest_property = min(room.current_properties)
        room.current_properties.remove(lowest_property)
        player.properties.append(lowest_property)
        
        # Calculate penalty: floor(currentBid / 2 / 1000) * 1000 is the refund, rest is penalty
        # Example: 3000 bid -> refund = floor(1500 / 1000) * 1000 = 1000, penalty = 2000
        if player.current_bid == 0:
            penalty = 0
        else:
            refund = (player.current_bid // 2 // 1000) * 1000
            penalty = player.current_bid - refund
        
        player.coins -= penalty
        player.current_bid = 0
        
        print(f"🚫 {player.nickname} passed. Got property {lowest_property}, paid penalty {penalty}")
        
        # Check if only one player remains
        active_players = [p for p in room.players.values() if not p.has_passed]
        print(f"📊 Active players remaining: {len(active_players)}/{len(room.players)}")
        for p in room.players.values():
            print(f"  - {p.nickname}: has_passed={p.has_passed}, current_bid={p.current_bid}")
        
        if len(active_players) == 1:
            # Last player gets highest property and pays full bid
            last_player = active_players[0]
            
            # Safety check: ensure there are properties available
            if not room.current_properties:
                print(f"⚠️ ERROR: No properties available for last player {last_player.nickname}!")
                self._cancel_turn_timer(room)
                await self._end_phase1_round(room)
                return room_id
            
            highest_property = max(room.current_properties)
            room.current_properties.remove(highest_property)
            last_player.properties.append(highest_property)
            bid_paid = last_player.current_bid
            last_player.coins -= last_player.current_bid
            last_player.current_bid = 0
            
            print(f"🏆 {last_player.nickname} wins the round! Got property {highest_property}, paid {bid_paid}")
            
            # Store the winner of this round (the last remaining player)
            # Find the player's sid
            for player_sid, p in room.players.items():
                if p == last_player:
                    room.last_round_winner = player_sid
                    break
            
            # Cancel timer - round is over
            self._cancel_turn_timer(room)
            
            # End of round
            await self._end_phase1_round(room)
        else:
            # Continue with next player
            has_active = await self._next_turn(room)
            
            if has_active:
                # Restart timer for next player
                await self._start_turn_timer(room)
            else:
                # Safety check: no active players found
                print("⚠️ Warning: No active players found after pass, ending round")
                self._cancel_turn_timer(room)
                await self._end_phase1_round(room)
        
        return room_id

    async def _next_turn(self, room: Room) -> bool:
        # Find next active player
        print(f"🔄 Looking for next active player...")
        attempts = 0
        start_index = room.current_turn_index
        while attempts < len(room.turn_order):
            room.current_turn_index = (room.current_turn_index + 1) % len(room.turn_order)
            current_player_sid = room.turn_order[room.current_turn_index]
            current_player = room.players[current_player_sid]
            
            print(f"  Checking {current_player.nickname} (has_passed={current_player.has_passed})")
            
            if not current_player.has_passed:
                print(f"✅ Next turn: {current_player.nickname}")
                return True  # Found an active player
            
            attempts += 1
        
        # No active player found (all have passed)
        print(f"⚠️ No active players found after checking all {len(room.turn_order)} players")
        return False

    async def _end_phase1_round(self, room: Room):
        print(f"🏁 Phase 1 round {room.round_number} ended")
        print(f"📦 Properties remaining in deck: {len(room.property_deck)}, Players: {len(room.players)}")
        
        # Broadcast current state before transitioning
        if self.sio:
            await self.broadcast_state(room.room_id, self.sio)
        
        # Wait a moment for players to see the results
        print(f"⏳ Waiting 2 seconds before starting next round...")
        await asyncio.sleep(2)
        
        # Check if more rounds needed
        if len(room.property_deck) >= len(room.players):
            # Start next round
            room.round_number += 1
            print(f"▶️ Starting Phase 1 round {room.round_number}")
            await self._start_phase1(room)
            
            # Broadcast state for new round
            if self.sio:
                await self.broadcast_state(room.room_id, self.sio)
        else:
            # Move to Phase 2
            print(f"🎯 Moving to Phase 2 (not enough properties left)")
            await self._start_phase2(room)

    async def _start_phase2(self, room: Room):
        room.phase = GamePhase.PHASE2_SELLING
        room.phase2_round_number = 1
        # Deal cheques equal to number of players
        num_players = len(room.players)
        room.current_cheques = sorted(room.cheque_deck[:num_players], reverse=True)
        room.cheque_deck = room.cheque_deck[num_players:]
        
        # Reset for card selection
        room.phase2_selections = {}
        for player in room.players.values():
            player.selected_property = None
        
        # Broadcast state to show Phase 2 has started
        if self.sio:
            await self.broadcast_state(room.room_id, self.sio)

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
        
        if player.selected_property is not None:  # Already selected a card
            return None
        
        player.selected_property = card_id  # Store selected card
        room.phase2_selections[sid] = card_id
        
        # Broadcast state to show player has selected (without revealing the card)
        if self.sio:
            await self.broadcast_state(room.room_id, self.sio)
        
        # Check if all players have selected
        if len(room.phase2_selections) == len(room.players):
            await self._resolve_phase2(room)
        
        return room_id

    async def _resolve_phase2(self, room: Room):
        # Sort players by selected card value (descending)
        player_cards = [(sid, player.selected_property) for sid, player in room.players.items()]
        player_cards.sort(key=lambda x: x[1], reverse=True)
        
        # Broadcast state to show all revealed cards (all_selected=True will show all cards)
        if self.sio:
            await self.broadcast_state(room.room_id, self.sio)
        
        # Wait a moment for players to see the reveal
        await asyncio.sleep(2)
        
        # Distribute cheques
        for i, (sid, card_value) in enumerate(player_cards):
            player = room.players[sid]
            player.properties.remove(card_value)
            player.cheques.append(room.current_cheques[i])
            player.selected_property = None
        
        # Clear selections for next round
        room.phase2_selections = {}
        
        # Broadcast state to show cheque distribution results
        if self.sio:
            await self.broadcast_state(room.room_id, self.sio)
        
        # Check if game over or continue
        if any(len(p.properties) > 0 for p in room.players.values()) and len(room.cheque_deck) >= len(room.players):
            # Continue to next Phase 2 round
            room.phase2_round_number += 1
            num_players = len(room.players)
            room.current_cheques = sorted(room.cheque_deck[:num_players], reverse=True)
            room.cheque_deck = room.cheque_deck[num_players:]
            
            # Broadcast state for next round
            if self.sio:
                await self.broadcast_state(room.room_id, self.sio)
        else:
            # Game over - calculate final scores
            room.phase = GamePhase.GAME_OVER
            
            # Broadcast final state
            if self.sio:
                await self.broadcast_state(room.room_id, self.sio)

    async def handle_disconnect(self, sid: str, sio):
        room_id = self.player_to_room.get(sid)
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            
            # 호스트가 나가는 경우 (첫 번째 플레이어)
            first_player_sid = next(iter(room.players.keys())) if room.players else None
            is_host_leaving = sid == first_player_sid
            
            # 플레이어가 존재하는지 확인
            player_exists = sid in room.players
            
            if player_exists:
                # 플레이어 삭제 전에 체크
                will_be_empty = len(room.players) <= 1
                
                # 플레이어 삭제
                del room.players[sid]
                
                if will_be_empty or is_host_leaving:
                    # 방 파괴 - 모든 플레이어에게 알림
                    await sio.emit('room:destroyed', {'message': '호스트가 나가서 방이 파괴되었습니다.'}, room=room_id)
                    del self.rooms[room_id]
                else:
                    # 남은 플레이어들에게 상태 업데이트
                    await self.broadcast_state(room_id, sio)
        
        if sid in self.player_to_room:
            del self.player_to_room[sid]

    async def broadcast_state(self, room_id: str, sio):
        if room_id not in self.rooms:
            return
        
        room = self.rooms[room_id]
        
        # Get first player (creator) as host
        first_player_sid = next(iter(room.players.keys())) if room.players else None
        
        # Check if all players have selected their cards in Phase 2
        all_selected = len(room.phase2_selections) == len(room.players) if room.phase == GamePhase.PHASE2_SELLING else False
        
        # Create a list of player IDs to avoid dictionary changed size during iteration error
        player_sids = list(room.players.keys())
        
        # Send individual state to each player
        for viewer_sid in player_sids:
            # Create player list with privacy handling
            players_list = []
            for i, (sid, p) in enumerate(room.players.items()):
                # Calculate total cheque value
                total_cheque_value = sum(p.cheques)
                
                # Determine what to show for selectedProperty
                # Only show if: it's the viewer's own card, OR all players have selected
                selected_property = None
                if sid == viewer_sid or all_selected:
                    selected_property = p.selected_property
                
                players_list.append({
                    'id': sid,
                    'nickname': p.nickname,
                    'avatar': f'👤',  # Default avatar
                    'isReady': p.ready,
                    'isHost': sid == first_player_sid,
                    'coins': p.coins,
                    'propertyCount': len(p.properties),
                    'properties': p.properties if sid == viewer_sid else [],  # Only show own properties
                    'chequeCount': len(p.cheques),
                    'cheques': p.cheques if sid == viewer_sid else [],  # Only show own cheques
                    'totalChequeValue': total_cheque_value,
                    'currentBid': p.current_bid,
                    'hasPassed': p.has_passed,
                    'isCurrentTurn': room.turn_order and len(room.turn_order) > room.current_turn_index and room.turn_order[room.current_turn_index] == sid,
                    'selectedProperty': selected_property,  # Privacy: only own card or after reveal
                    'hasSelected': p.selected_property is not None  # Phase 2: whether player has selected
                })
            
            # Create state object for this specific viewer
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
                'roundNumber': room.round_number,
                'phase2RoundNumber': room.phase2_round_number,
                'allPlayersSelected': all_selected
            }
            
            # Send to specific player
            await sio.emit('room:state', state, room=viewer_sid)