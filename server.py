import asyncio
import json
import random
import http.server
import socketserver
import websockets
import threading
import os
import time

# --- Game Logic (Server Side) ---

class Deck:
    def __init__(self):
        self.suits = ['♠', '♥', '♦', '♣']
        self.values = [
            {'val': 1, 'display': 'A'}, {'val': 2, 'display': '2'}, {'val': 3, 'display': '3'},
            {'val': 4, 'display': '4'}, {'val': 5, 'display': '5'}, {'val': 6, 'display': '6'},
            {'val': 7, 'display': '7'}, {'val': 8, 'display': '8'}, {'val': 9, 'display': '9'},
            {'val': 10, 'display': '10'}, {'val': 11, 'display': 'J'}, {'val': 12, 'display': 'Q'},
            {'val': 13, 'display': 'K'}
        ]
        self.cards = []
        self.reset()

    def reset(self):
        self.cards = []
        for suit in self.suits:
            for v in self.values:
                color = 'red' if suit in ['♥', '♦'] else 'black'
                self.cards.append({**v, 'suit': suit, 'color': color})
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def draw(self):
        if not self.cards:
            self.reset()
        return self.cards.pop()

class GameState:
    def __init__(self):
        self.deck = Deck()
        self.players = []  # [{id, name, balance, connected}]
        self.pot = 0
        self.ante = 10
        self.round_phase = 'WAITING'  # WAITING | IN_ROUND
        self.player_states = {}  # session_id -> {cards, phase, result_msg, bet, choice}
        self.message = "Waiting for players..."
        self.last_update_id = 0

    def add_player(self, session_id, name):
        for p in self.players:
            if p['id'] == session_id:
                return p

        player = {
            'id': session_id,
            'name': name,
            'balance': 1000,
            'connected': True
        }
        self.players.append(player)
        self.player_states[session_id] = {
            'cards': {'left': None, 'right': None, 'result': None},
            'phase': 'IDLE',
            'result_msg': '',
            'bet': 0,
            'choice': None
        }
        self.message = f"{name} joined the game."
        self.last_update_id += 1
        return player

    def remove_player(self, session_id):
        idx = -1
        for i, p in enumerate(self.players):
            if p['id'] == session_id:
                idx = i
                break

        if idx != -1:
            removed = self.players.pop(idx)
            if session_id in self.player_states:
                del self.player_states[session_id]
            self.message = f"{removed['name']} disconnected."
            self.last_update_id += 1
            # Check if round completes after removal
            if self.round_phase == 'IN_ROUND':
                self._check_round_complete()

    def get_state_for_player(self, session_id):
        ps = self.player_states.get(session_id, {
            'cards': {'left': None, 'right': None, 'result': None},
            'phase': 'IDLE',
            'result_msg': '',
            'bet': 0,
            'choice': None
        })

        # Build public player list with status
        players_public = []
        for p in self.players:
            sid = p['id']
            pstate = self.player_states.get(sid, {})
            players_public.append({
                'id': sid,
                'name': p['name'],
                'balance': p['balance'],
                'phase': pstate.get('phase', 'IDLE'),
                'result_msg': pstate.get('result_msg', '')
            })

        return {
            'players': players_public,
            'pot': self.pot,
            'round_phase': self.round_phase,
            'my_cards': ps.get('cards', {'left': None, 'right': None, 'result': None}),
            'my_phase': ps.get('phase', 'IDLE'),
            'my_result_msg': ps.get('result_msg', ''),
            'message': self.message,
            'ante': self.ante,
            'update_id': self.last_update_id
        }

    # --- Actions ---

    def handle_action(self, session_id, action_type, payload):
        if not self.players:
            return

        if action_type == 'DEAL':
            if self.round_phase == 'WAITING' and len(self.players) >= 1:
                self.deal_all()
            return

        # Per-player actions
        ps = self.player_states.get(session_id)
        if not ps:
            return

        player = None
        for p in self.players:
            if p['id'] == session_id:
                player = p
                break
        if not player:
            return

        if action_type == 'SHOOT':
            self._place_bet(player, ps, int(payload.get('bet', 0)))
        elif action_type == 'SHOOT_SPECIAL':
            self._place_bet(player, ps, int(payload.get('bet', 0)), payload.get('choice'))
        elif action_type == 'PASS':
            self._pass(player, ps)

        self._check_all_bets_placed()

    def deal_all(self):
        """Deal a gate to every player simultaneously."""
        # Ante: deduct from all players every deal
        for p in self.players:
            if p['balance'] >= self.ante:
                p['balance'] -= self.ante
                self.pot += self.ante

        # Deal cards to each player
        for p in self.players:
            sid = p['id']
            c1 = self.deck.draw()
            c2 = self.deck.draw()
            ps = self.player_states[sid]
            ps['cards'] = {'left': c1, 'right': c2, 'result': None}
            ps['result_msg'] = ''
            ps['bet'] = 0
            ps['choice'] = None

            diff = abs(c1['val'] - c2['val'])
            if diff == 0:
                ps['phase'] = 'SHOOTING_SPECIAL'
            elif diff == 1:
                # Auto-pass for consecutive
                ps['phase'] = 'DONE'
                ps['result_msg'] = 'Consecutive! Auto Pass.'
            else:
                ps['phase'] = 'SHOOTING'

        self.round_phase = 'IN_ROUND'
        self.message = "Cards dealt! Place your bets."
        self.last_update_id += 1

        # Check if all auto-passed (unlikely but possible)
        self._check_all_bets_placed()

    def _place_bet(self, player, ps, bet, choice=None):
        """Player places a bet. Does NOT resolve yet — waits for all players."""
        if ps['phase'] not in ('SHOOTING', 'SHOOTING_SPECIAL'):
            return
        if bet <= 0:
            return
        ps['bet'] = bet
        ps['choice'] = choice  # None for normal, 'high'/'low' for special
        ps['phase'] = 'BET_PLACED'
        ps['result_msg'] = 'Bet placed. Waiting...'
        self.last_update_id += 1

    def _pass(self, player, ps):
        if ps['phase'] not in ('SHOOTING', 'SHOOTING_SPECIAL', 'FORCED_PASS'):
            return
        ps['phase'] = 'DONE'
        ps['bet'] = 0
        ps['result_msg'] = 'Passed.'
        self.last_update_id += 1

    def _check_all_bets_placed(self):
        """Check if all players have bet or passed. If so, resolve the round."""
        if self.round_phase != 'IN_ROUND':
            return
        all_decided = all(
            self.player_states[p['id']]['phase'] in ('BET_PLACED', 'DONE')
            for p in self.players
            if p['id'] in self.player_states
        )
        if all_decided:
            self._resolve_round()

    def _resolve_round(self):
        """Resolve all bets simultaneously with proportional pot distribution."""
        # Step 1: Draw result cards and determine outcome for each bettor
        results = []  # [{player, ps, outcome, raw_win, raw_loss}]

        for p in self.players:
            sid = p['id']
            ps = self.player_states.get(sid)
            if not ps or ps['phase'] != 'BET_PLACED':
                continue  # Already DONE (passed / auto-passed)

            bet = ps['bet']
            res = self.deck.draw()
            ps['cards']['result'] = res

            if ps['choice'] is not None:
                # Special gate (pair)
                outcome = self._judge_special(ps, res)
            else:
                # Normal gate
                outcome = self._judge_normal(ps, res)

            results.append({
                'player': p,
                'ps': ps,
                'outcome': outcome,  # 'win', 'hit_post', 'miss', 'loss', 'triple_post'
                'bet': bet
            })

        # Step 2: Process losers first (add their losses to pot)
        for r in results:
            bet = r['bet']
            player = r['player']
            ps = r['ps']
            if r['outcome'] == 'hit_post' or r['outcome'] == 'triple_post':
                penalty = bet * 2
                actual_loss = min(penalty, player['balance'])
                player['balance'] -= actual_loss
                self.pot += actual_loss
                label = 'HIT POST' if r['outcome'] == 'hit_post' else 'TRIPLE POST'
                ps['result_msg'] = f"{label}! -${actual_loss}"
                ps['phase'] = 'DONE'
            elif r['outcome'] in ('miss', 'loss'):
                actual_loss = min(bet, player['balance'])
                player['balance'] -= actual_loss
                self.pot += actual_loss
                label = 'MISS' if r['outcome'] == 'miss' else 'LOSS'
                ps['result_msg'] = f"{label}! -${actual_loss}"
                ps['phase'] = 'DONE'

        # Step 3: Distribute winnings to winners (proportionally if needed)
        winners = [r for r in results if r['outcome'] == 'win']
        if winners:
            total_wanted = sum(w['bet'] for w in winners)
            available = self.pot

            if total_wanted <= available:
                # Enough in pot — pay full
                for w in winners:
                    w['player']['balance'] += w['bet']
                    self.pot -= w['bet']
                    w['ps']['result_msg'] = f"WIN! +${w['bet']}"
                    w['ps']['phase'] = 'DONE'
            else:
                # Not enough — distribute proportionally by bet
                for w in winners:
                    ratio = w['bet'] / total_wanted
                    payout = int(available * ratio)
                    w['player']['balance'] += payout
                    self.pot -= payout
                    w['ps']['result_msg'] = f"WIN! +${payout} (pot split)"
                    w['ps']['phase'] = 'DONE'

        # Step 4: Round complete
        self.round_phase = 'WAITING'
        self.message = "Round complete! Anyone can click Deal."
        self.last_update_id += 1
        self._check_redistribute()

    def _judge_normal(self, ps, res):
        """Judge a normal gate shot. Returns 'win', 'hit_post', or 'miss'."""
        c1 = ps['cards']['left']['val']
        c2 = ps['cards']['right']['val']
        r = res['val']
        ma, mi = max(c1, c2), min(c1, c2)
        if mi < r < ma:
            return 'win'
        elif r == c1 or r == c2:
            return 'hit_post'
        else:
            return 'miss'

    def _judge_special(self, ps, res):
        """Judge a special gate shot (pair). Returns 'win', 'triple_post', or 'loss'."""
        gate = ps['cards']['left']['val']
        r = res['val']
        choice = ps['choice']
        if r == gate:
            return 'triple_post'
        if (choice == 'high' and r > gate) or (choice == 'low' and r < gate):
            return 'win'
        return 'loss'

    def _check_redistribute(self):
        """If any player has balance <= 0, redistribute pot evenly to all players."""
        if not self.players:
            return
        any_broke = any(p['balance'] <= 0 for p in self.players)
        if not any_broke:
            return

        if self.pot <= 0:
            # If pot is empty and someone is broke, game over or admin inject?
            # For now, just return. Game might need restart.
            return

        total_pot = self.pot
        n = len(self.players)
        share = total_pot // n
        remainder = total_pot - (share * n)

        for p in self.players:
            p['balance'] += share

        self.pot = remainder  # leftover cents go to pot
        self.message = f"💰 A player went broke! Pot (${total_pot}) distributed evenly (+${share} each)."
        self.last_update_id += 1


game = GameState()

# --- WebSocket Server ---

connected_clients = {}  # websocket -> session_id
client_last_activity = {}  # websocket -> timestamp
IDLE_TIMEOUT = 180  # 3 minutes in seconds

async def broadcast_personalized_state():
    for ws, sid in list(connected_clients.items()):
        if sid:
            state = game.get_state_for_player(sid)
            try:
                await ws.send(json.dumps({'type': 'STATE', 'state': state}))
            except Exception:
                pass

async def idle_checker():
    """Periodically check for idle clients and disconnect them."""
    while True:
        await asyncio.sleep(30)  # Check every 30 seconds
        now = time.time()
        idle_clients = []
        for ws, last in list(client_last_activity.items()):
            if now - last > IDLE_TIMEOUT:
                idle_clients.append(ws)
        for ws in idle_clients:
            sid = connected_clients.get(ws)
            player_name = 'Unknown'
            if sid:
                for p in game.players:
                    if p['id'] == sid:
                        player_name = p['name']
                        break
            print(f"Kicking idle player: {player_name} ({sid})")
            try:
                await ws.send(json.dumps({'type': 'ERROR', 'msg': 'You have been disconnected due to inactivity (3 min).'}))
                await ws.close()
            except Exception:
                pass

async def ws_handler(websocket):
    session_id = str(id(websocket))
    print(f"New connection: {session_id}")
    client_last_activity[websocket] = time.time()

    try:
        async for message in websocket:
            # Update activity timestamp on every message
            client_last_activity[websocket] = time.time()

            data = json.loads(message)
            req_type = data.get('type')

            if req_type == 'JOIN':
                name = data.get('name', 'Guest')
                ante = data.get('ante', 10)
                player = game.add_player(session_id, name)
                game.ante = max(1, int(ante))  # Update ante (last joiner's setting wins)
                connected_clients[websocket] = session_id
                await websocket.send(json.dumps({'type': 'WELCOME', 'your_id': player['id']}))

            elif req_type == 'ACTION':
                game.handle_action(session_id, data.get('action'), data.get('payload', {}))

            # Broadcast personalized state to each client
            await broadcast_personalized_state()

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if websocket in connected_clients:
            del connected_clients[websocket]
        if websocket in client_last_activity:
            del client_last_activity[websocket]
        game.remove_player(session_id)
        await broadcast_personalized_state()

async def start_ws():
    async with websockets.serve(ws_handler, "0.0.0.0", 8765):
        print("WebSocket Server started on port 8765")
        # Start idle checker in the background
        asyncio.create_task(idle_checker())
        print(f"Idle timeout checker started ({IDLE_TIMEOUT}s)")
        await asyncio.Future()

# --- HTTP Server (Static Files) ---
def start_http():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    handler = http.server.SimpleHTTPRequestHandler
    port = int(os.environ.get("PORT", 8000))
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"HTTP Server started on port {port}")
        httpd.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=start_http, daemon=True)
    t.start()

    try:
        asyncio.run(start_ws())
    except KeyboardInterrupt:
        print("Stopping...")
