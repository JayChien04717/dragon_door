// --- WebSocket Client for Shoot the Gate ---

const WS_URL = `ws://${window.location.hostname}:8765`;

let ws;
let myPlayerId = null;

// DOM Elements
const els = {
    loginModal: document.getElementById('login-modal'),
    usernameInput: document.getElementById('username-input'),
    joinBtn: document.getElementById('join-btn'),
    connStatus: document.getElementById('connection-status'),
    pot: document.getElementById('pot-display'),
    msg: document.getElementById('message-area'),
    cardLeft: document.getElementById('card-left'),
    cardRight: document.getElementById('card-right'),
    cardResult: document.getElementById('card-result'),
    betSlider: document.getElementById('bet-slider'),
    betDisplay: document.getElementById('current-bet-display'),
    btnDeal: document.getElementById('deal-btn'),
    btnShoot: document.getElementById('shoot-btn'),
    btnPass: document.getElementById('pass-btn'),
    highLowControls: document.getElementById('high-low-controls'),
    myStatus: document.getElementById('my-status'),
    playersContainer: document.getElementById('players-container'),
    timerBarContainer: document.getElementById('timer-bar-container'),
    timerBar: document.getElementById('timer-bar'),
    countdownText: document.getElementById('countdown-text')
};

// --- Timer State ---
let timerInterval = null;
let prevMyPhase = 'IDLE';
let prevRoundPhase = 'WAITING';

// --- WebSocket Connection ---
function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        els.connStatus.innerText = 'Connected! Enter your name.';
        els.connStatus.style.color = '#10b981';
        els.joinBtn.disabled = false;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'WELCOME') {
            myPlayerId = data.your_id;
            els.loginModal.classList.add('hidden');
        } else if (data.type === 'STATE') {
            renderState(data.state);
        } else if (data.type === 'ERROR') {
            alert(data.msg);
            // If kicked for inactivity, show login modal to allow rejoin
            if (data.msg.includes('inactivity')) {
                myPlayerId = null;
                els.loginModal.classList.remove('hidden');
            }
        }
    };

    ws.onclose = () => {
        els.connStatus.innerText = 'Disconnected. Reconnecting...';
        els.connStatus.style.color = '#ef4444';
        setTimeout(connect, 3000);
    };

    ws.onerror = () => {
        els.connStatus.innerText = 'Connection error.';
        els.connStatus.style.color = '#ef4444';
    };
}

// --- Join ---
els.joinBtn.addEventListener('click', () => {
    const name = els.usernameInput.value.trim();
    if (!name) return;
    const ante = parseInt(document.getElementById('ante-input').value) || 10;
    ws.send(JSON.stringify({ type: 'JOIN', name, ante }));
});

els.usernameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') els.joinBtn.click();
});

// --- Actions ---
els.btnDeal.addEventListener('click', () => {
    ws.send(JSON.stringify({ type: 'ACTION', action: 'DEAL', payload: {} }));
});

els.btnShoot.addEventListener('click', () => {
    const bet = parseInt(els.betSlider.value);
    ws.send(JSON.stringify({ type: 'ACTION', action: 'SHOOT', payload: { bet } }));
});

els.btnPass.addEventListener('click', () => {
    ws.send(JSON.stringify({ type: 'ACTION', action: 'PASS', payload: {} }));
});

document.querySelectorAll('.choice-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const choice = e.target.dataset.choice;
        const bet = parseInt(els.betSlider.value);
        ws.send(JSON.stringify({ type: 'ACTION', action: 'SHOOT_SPECIAL', payload: { bet, choice } }));
    });
});

els.betSlider.addEventListener('input', (e) => {
    els.betDisplay.innerText = `$${e.target.value}`;
});

// --- Render Card ---
function renderCard(el, card) {
    if (!card) {
        el.innerHTML = '<div class="card-back">🂠</div>';
        el.className = 'card card-empty';
        return;
    }
    el.innerHTML = `
        <div class="card-corner top-left-corner">
            <span class="card-value">${card.display}</span>
            <span class="card-suit-small">${card.suit}</span>
        </div>
        <div class="card-center-suit">${card.suit}</div>
        <div class="card-corner bottom-right-corner">
            <span class="card-value">${card.display}</span>
            <span class="card-suit-small">${card.suit}</span>
        </div>
    `;
    el.className = `card card-face ${card.color}`;
}

// --- Render Players ---
function renderPlayers(players) {
    els.playersContainer.innerHTML = '';

    players.forEach((p) => {
        const div = document.createElement('div');
        div.className = 'player-avatar';

        const isMe = p.id === myPlayerId;
        if (isMe) div.classList.add('is-me');

        // Show phase status
        let statusIcon = '';
        if (p.phase === 'DONE') {
            statusIcon = p.result_msg.startsWith('WIN') ? '✅' : (p.result_msg.startsWith('Passed') || p.result_msg.startsWith('Consecutive') ? '⏭️' : '❌');
        } else if (p.phase === 'BET_PLACED') {
            statusIcon = '💰';
        } else if (p.phase === 'SHOOTING' || p.phase === 'SHOOTING_SPECIAL') {
            statusIcon = '🎯';
        } else if (p.phase === 'IDLE') {
            statusIcon = '⏳';
        }

        div.innerHTML = `
            <div class="avatar-icon">${isMe ? '🙋' : '👤'}</div>
            <div class="player-info">
                <span class="name">${p.name}${isMe ? ' (You)' : ''}</span>
                <span class="balance">$${p.balance}</span>
            </div>
            <div class="player-status-icon">${statusIcon}</div>
        `;

        els.playersContainer.appendChild(div);
    });
}

// --- Timer Bar ---
function startTimerBar(deadline) {
    stopTimerBar();
    els.timerBarContainer.classList.remove('hidden');
    const totalDuration = 5; // 5 seconds

    timerInterval = setInterval(() => {
        const now = Date.now() / 1000;
        const remaining = Math.max(0, deadline - now);
        const pct = (remaining / totalDuration) * 100;
        els.timerBar.style.width = `${pct}%`;
        els.countdownText.innerText = Math.ceil(remaining);
        if (remaining <= 0) {
            stopTimerBar();
        }
    }, 50);
}

function stopTimerBar() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
    els.timerBarContainer.classList.add('hidden');
    els.timerBar.style.width = '100%';
    els.countdownText.innerText = '';
}


// --- Render Full State ---
function renderState(state) {
    // Players
    renderPlayers(state.players);

    // Pot
    els.pot.innerText = `$${state.pot}`;

    // Message
    els.msg.innerText = state.message;

    // My cards
    renderCard(els.cardLeft, state.my_cards.left);
    renderCard(els.cardRight, state.my_cards.right);
    renderCard(els.cardResult, state.my_cards.result);

    // My status message
    if (state.my_result_msg) {
        els.myStatus.innerText = state.my_result_msg;
        els.myStatus.classList.remove('hidden');
    } else {
        els.myStatus.classList.add('hidden');
    }

    // --- Track phase ---
    const myPhase = state.my_phase;
    const roundPhase = state.round_phase;
    prevMyPhase = myPhase;

    // --- Timer bar: show during IN_ROUND when player needs to decide ---
    if (roundPhase === 'IN_ROUND' && (myPhase === 'SHOOTING' || myPhase === 'SHOOTING_SPECIAL')) {
        if (state.decision_deadline && !timerInterval) {
            startTimerBar(state.decision_deadline);
        }
    } else {
        stopTimerBar();
    }
    prevRoundPhase = roundPhase;

    // Controls
    els.highLowControls.classList.add('hidden');

    if (roundPhase === 'WAITING') {
        // Anyone can start the game
        els.btnDeal.disabled = false;
        els.btnDeal.innerText = 'Start Game';
        els.btnShoot.disabled = true;
        els.btnPass.disabled = true;
        els.betSlider.disabled = true;
    } else if (roundPhase === 'COUNTDOWN') {
        // Auto-deal countdown — disable everything
        els.btnDeal.disabled = true;
        els.btnDeal.innerText = 'Dealing...';
        els.btnShoot.disabled = true;
        els.btnPass.disabled = true;
        els.betSlider.disabled = true;
    } else if (roundPhase === 'IN_ROUND') {
        els.btnDeal.disabled = true;
        els.btnDeal.innerText = 'In Round';

        if (myPhase === 'SHOOTING') {
            els.btnShoot.disabled = false;
            els.btnPass.disabled = false;
            els.betSlider.disabled = false;
            const me = state.players.find(p => p.id === myPlayerId);
            const maxBet = Math.min(state.pot > 0 ? state.pot : 1, me ? me.balance : 1);
            els.betSlider.max = maxBet > 0 ? maxBet : 1;
            if (parseInt(els.betSlider.value) > maxBet) els.betSlider.value = maxBet;
            els.betDisplay.innerText = `$${els.betSlider.value}`;
        } else if (myPhase === 'SHOOTING_SPECIAL') {
            els.btnShoot.disabled = true;
            els.btnPass.disabled = false;
            els.betSlider.disabled = false;
            els.highLowControls.classList.remove('hidden');
            const me = state.players.find(p => p.id === myPlayerId);
            const maxBet = Math.min(state.pot > 0 ? state.pot : 1, me ? me.balance : 1);
            els.betSlider.max = maxBet > 0 ? maxBet : 1;
            if (parseInt(els.betSlider.value) > maxBet) els.betSlider.value = maxBet;
            els.betDisplay.innerText = `$${els.betSlider.value}`;
        } else {
            // BET_PLACED, DONE, or IDLE — disable controls
            els.btnShoot.disabled = true;
            els.btnPass.disabled = true;
            els.betSlider.disabled = true;
        }
    }
}

// --- Init ---
connect();
