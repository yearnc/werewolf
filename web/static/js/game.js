// === Werewolf Web UI — SSE client & rendering ===

let currentState = null;
let eventCount = 0;
let selectedTargets = [];
let typingIndicator = null;
let lastSpeechEventCount = 0;
let typingTimeout = null;

// ── Avatar Colors ────────────────────────────────────

var AVATAR_COLORS = [
    '#e06060', '#e09830', '#b8b840', '#50b850', '#4098c0',
    '#6060d0', '#9858c0', '#d05898', '#50a098'
];

function getAvatarColor(playerId) {
    return AVATAR_COLORS[(playerId - 1) % AVATAR_COLORS.length];
}

function getPlayerRole(state, playerId) {
    if (!state.players) return '';
    for (var i = 0; i < state.players.length; i++) {
        if (state.players[i].id === playerId) return state.players[i].role;
    }
    return '';
}

// ── Particle System ──────────────────────────────────

(function initParticles() {
    const container = document.getElementById('particles');
    if (!container) return;
    const colors = ['gold', 'white', 'emerald'];
    for (let i = 0; i < 20; i++) {
        const p = document.createElement('div');
        p.className = 'particle ' + colors[Math.floor(Math.random() * colors.length)];
        p.style.left = Math.random() * 100 + '%';
        p.style.width = p.style.height = (Math.random() * 2.5 + 1) + 'px';
        p.style.animationDuration = (Math.random() * 12 + 10) + 's';
        p.style.animationDelay = Math.random() * 12 + 's';
        container.appendChild(p);
    }
})();

// ── SSE Connection ──────────────────────────────────

function connectSSE() {
    const es = new EventSource('/api/stream');
    es.onmessage = function (e) {
        try {
            const state = JSON.parse(e.data);
            if (state.error) { console.error(state.error); return; }
            currentState = state;
            renderState(state);
        } catch (err) {
            console.error('SSE parse error:', err);
        }
    };
    es.onerror = function () {
        console.warn('SSE disconnected, reconnecting in 2s...');
        es.close();
        setTimeout(connectSSE, 2000);
    };
}

// ── Main Render ─────────────────────────────────────

function renderState(state) {
    updateHeader(state);
    updatePlayerGrid(state);
    updateEventLog(state);
    updateDecisionZone(state);

    if (state.human_role_info && !state._role_shown) {
        showRoleOverlay(state.human_role_info);
        state._role_shown = true;
    }

    if (state.game_over) {
        showGameOver(state);
    }
}

// ── Header ──────────────────────────────────────────

function updateHeader(state) {
    if (state.phase == null) return;

    // Phase-based body background class
    const prevClass = document.body.className;
    const newClass = (state.phase || 'setup') + '-phase';
    if (prevClass !== newClass) {
        document.body.className = newClass;
    }

    const icons = {
        setup: '🃏', night: '🌙', day_announce: '☀️',
        sheriff_election: '🎖️', speaking: '🎤', voting: '🗳️', game_over: '🏁'
    };
    const labels = {
        setup: '准备中', night: '夜晚', day_announce: '白天',
        sheriff_election: '警长竞选', speaking: '发言中', voting: '投票放逐', game_over: '游戏结束'
    };
    document.getElementById('phase-icon').textContent = icons[state.phase] || '🐺';
    document.getElementById('phase-text').textContent = labels[state.phase] || state.phase;

    var nc = document.getElementById('night-count');
    var dc = document.getElementById('day-count');
    if (state.phase === 'setup') {
        nc.textContent = '--';
        dc.textContent = '--';
    } else {
        nc.textContent = '第' + (state.night == null ? '?' : state.night) + '夜';
        dc.textContent = '第' + (state.day == null ? '?' : state.day) + '天';
    }

    const sheriffBadge = document.getElementById('sheriff-badge');
    if (state.sheriff_id) {
        sheriffBadge.style.display = '';
        document.getElementById('sheriff-name').textContent =
            '玩家' + state.sheriff_id + '号';
    } else {
        sheriffBadge.style.display = 'none';
    }
}

// ── Player Sidebar ──────────────────────────────────

function updatePlayerGrid(state) {
    if (!state.players) return;
    const list = document.getElementById('player-list');
    if (!list) return;
    list.innerHTML = '';

    state.players.forEach(function (p) {
        const card = document.createElement('div');
        card.className = 'player-card';
        if (p.is_alive) card.classList.add('alive');
        else card.classList.add('dead');
        if (p.is_sheriff) card.classList.add('sheriff');
        if (p.is_human && state.human_player_id) card.classList.add('human');
        if (p.is_ally) card.classList.add('ally');
        card.setAttribute('data-player-id', p.id);

        let badgeHtml = '';
        if (p.is_sheriff) badgeHtml += '<span class="sheriff-star">⭐</span>';
        if (p.is_human) badgeHtml += '<span class="human-badge">👤</span>';
        if (p.is_ally) badgeHtml += '<span class="ally-badge">🐺</span>';

        card.innerHTML =
            '<span class="player-card-index">' + p.id + '</span>' +
            '<span class="player-card-info">' +
                '<div class="player-role">' + p.role + '</div>' +
                '<div class="player-status">' + (p.is_alive ? '生存' : '💀 死亡') + '</div>' +
            '</span>' +
            badgeHtml;

        list.appendChild(card);
    });
}

// ── Event Log ───────────────────────────────────────

var SPEECH_EVENT_TYPES = { speech: true, campaign_speech: true, wolf_discuss: true };

function updateEventLog(state) {
    const inner = document.getElementById('event-log-inner');
    const events = state.events || [];
    if (events.length === 0 || events.length === eventCount) return;

    if (events.length < eventCount) {
        inner.innerHTML = '';
        eventCount = 0;
        lastSpeechEventCount = 0;
        removeTypingIndicator();
    }

    // Check if new speech events were added (AI is "speaking")
    var newSpeechCount = 0;
    for (var i = eventCount; i < events.length; i++) {
        if (SPEECH_EVENT_TYPES[events[i].type]) newSpeechCount++;
    }

    for (var i = eventCount; i < events.length; i++) {
        var ev = events[i];
        if (SPEECH_EVENT_TYPES[ev.type]) {
            renderSpeechBubble(inner, ev, state);
        } else {
            renderSystemMsg(inner, ev);
        }
    }
    eventCount = events.length;

    // Show typing indicator if AI players are about to speak
    // (when the phase is speaking/voting/campaign and no human decision pending)
    if (newSpeechCount > 0 && !state.waiting_for_human &&
        (state.phase === 'speaking' || state.phase === 'sheriff_election' || state.phase === 'voting')) {
        lastSpeechEventCount = eventCount;
        // If no new events come in within 1.5s, show typing indicator
        clearTimeout(typingTimeout);
        typingTimeout = setTimeout(function () {
            if (eventCount === lastSpeechEventCount && !currentState.waiting_for_human) {
                showTypingIndicator(inner);
            }
        }, 1500);
    } else {
        removeTypingIndicator();
    }

    // Show/hide waiting hint for multi-player AI decision phases
    updateWaitingHint(inner, state);

    // Auto-scroll
    const log = document.getElementById('event-log');
    log.scrollTop = log.scrollHeight;
}

function showTypingIndicator(inner) {
    if (typingIndicator) return;
    typingIndicator = document.createElement('div');
    typingIndicator.className = 'typing-indicator';
    // Avatar
    var avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.textContent = '...';
    avatar.style.background = '#3a4a5a';
    typingIndicator.appendChild(avatar);
    // Dots
    var dots = document.createElement('div');
    dots.className = 'typing-dots';
    dots.innerHTML = '<span></span><span></span><span></span>';
    typingIndicator.appendChild(dots);
    inner.appendChild(typingIndicator);
}

function removeTypingIndicator() {
    clearTimeout(typingTimeout);
    if (typingIndicator && typingIndicator.parentNode) {
        typingIndicator.parentNode.removeChild(typingIndicator);
    }
    typingIndicator = null;
}

// ── Waiting Notice (header day-night box) ─────────────

var MULTI_DECISION_PHASES = {
    sheriff_election: 'AI 玩家正在逐个参选、竞选宣言...',
    speaking:        'AI 玩家正在轮流发言中...',
    voting:          'AI 玩家正在逐个投票中...',
    night:           '夜晚行动中，各角色正在使用技能...'
};

function updateWaitingHint(inner, state) {
    var notice = document.getElementById('waiting-notice');
    if (!notice) return;
    var msg = MULTI_DECISION_PHASES[state.phase];
    if (msg && !state.waiting_for_human && !state.game_over) {
        notice.textContent = msg;
        notice.style.display = '';
    } else {
        notice.style.display = 'none';
        notice.textContent = '';
    }
}

function renderSpeechBubble(inner, ev, state) {
    removeTypingIndicator();

    var isSelf = ev.player_id === state.human_player_id;
    var isCampaign = ev.type === 'campaign_speech';
    var isWolf = ev.type === 'wolf_discuss';

    var text = ev.text;
    var colonIdx = text.indexOf('：');
    var speaker, message;
    if (colonIdx >= 0) {
        speaker = text.substring(0, colonIdx);
        message = text.substring(colonIdx + 1);
    } else {
        speaker = '';
        message = text;
    }

    var playerNum = ev.player_id || '?';
    var role = getPlayerRole(state, ev.player_id);
    var avatarColor = getAvatarColor(ev.player_id);

    var row = document.createElement('div');
    row.className = 'chat-row ' + (isSelf ? 'self' : 'other');

    // Avatar circle
    var avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.textContent = playerNum;
    avatar.style.background = avatarColor;
    row.appendChild(avatar);

    // Body: name + bubble
    var body = document.createElement('div');
    body.className = 'chat-body';

    // Name line
    var nameEl = document.createElement('div');
    nameEl.className = 'chat-name';
    if (isSelf) {
        nameEl.textContent = '你 · ' + role;
    } else {
        var displayName = speaker || ('玩家' + playerNum + '号');
        if (role) displayName += ' · ' + role;
        nameEl.textContent = displayName;
    }
    body.appendChild(nameEl);

    // Bubble
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble ' + (isSelf ? 'self' : 'other');
    if (isWolf) bubble.classList.add('wolf');
    if (isCampaign) bubble.classList.add('campaign');
    bubble.textContent = message;
    body.appendChild(bubble);

    row.appendChild(body);
    inner.appendChild(row);
}

function renderSystemMsg(inner, ev) {
    removeTypingIndicator();
    var div = document.createElement('div');
    div.className = 'chat-system ' + ev.type;
    div.textContent = ev.text;
    inner.appendChild(div);
}

// ── Decision Zone ───────────────────────────────────

function updateDecisionZone(state) {
    const zone = document.getElementById('decision-zone');
    if (!state.waiting_for_human) {
        zone.style.display = 'none';
        zone.innerHTML = '';
        clearSelection();
        return;
    }

    const dtype = state.decision_type;
    const ctx = state.decision_context || {};
    const did = state.decision_id;

    if (zone.dataset.decisionId === did && zone.style.display !== 'none') {
        return;
    }

    const savedTarget = (selectedTargets.length > 0) ? selectedTargets[0] : null;

    zone.dataset.decisionId = did;
    zone.style.display = '';
    let html = '';
    switch (dtype) {
        case 'wolf_discussion':
            html = renderFreeSpeech(did, ctx, '🐺 狼人讨论发言', false);
            break;
        case 'wolf_kill':
            html = renderTargetSelect(did, ctx, '🔪 选择今晚的击杀目标');
            break;
        case 'seer_check':
            html = renderTargetSelect(did, ctx, '🔮 选择查验目标');
            break;
        case 'witch_decision':
            html = renderWitchDecision(did, ctx);
            break;
        case 'hunter_shot':
            html = renderTargetSelect(did, ctx, '🔫 选择开枪目标（可选放弃）', true);
            break;
        case 'sheriff_candidacy':
            html = renderYesNo(did, ctx, '🎖️ 是否参加警长竞选？');
            break;
        case 'campaign_speech':
            html = renderFreeSpeech(did, ctx, '🎤 发表竞选宣言', false);
            break;
        case 'sheriff_vote':
            html = renderTargetSelect(did, ctx, '🗳️ 选择你支持的警长候选人');
            break;
        case 'sheriff_successor':
            html = renderTargetSelect(did, ctx, '🎖️ 选择警徽继任者');
            break;
        case 'day_speech':
            html = renderFreeSpeech(did, ctx, '🗣️ 发表你的发言', false);
            break;
        case 'elimination_vote':
            html = renderTargetSelect(did, ctx, '🗳️ 选择放逐目标（可选弃票）', true, false);
            break;
        default:
            html = '<p style="color:var(--text-secondary);padding:12px;">等待你的决策...</p>';
    }

    zone.innerHTML = html;
    bindDecisionEvents(did, dtype, ctx);

    if (savedTarget != null) {
        selectedTargets = [savedTarget];
        const btn = document.querySelector(
            '.target-btn[data-target="' + savedTarget + '"], .decision-btn.skip[data-target="' + savedTarget + '"]'
        );
        if (btn) {
            applySelectedInline(btn);
        }
        const submitBtn = document.querySelector('.submit-targets');
        if (submitBtn) submitBtn.disabled = false;
    }
}

// ── Decision UI Renderers ───────────────────────────

function renderTargetSelect(did, ctx, title, allowSkip, showContext) {
    let html = '<div class="decision-title">' + title + '</div>';

    if (showContext !== false) {
        if (ctx.death_summary) {
            html += '<div class="decision-context">' + ctx.death_summary + '</div>';
        }
        if (ctx.private_info) {
            html += '<div class="decision-context">' + ctx.private_info + '</div>';
        }
        if (ctx.allies && ctx.allies.length) {
            html += '<div class="decision-context">🐺 你的狼队友：' + ctx.allies.join('、') + '</div>';
        }
        if (ctx.suspicions && ctx.suspicions !== '（暂无怀疑对象）') {
            html += '<div class="decision-context">怀疑对象：' + ctx.suspicions + '</div>';
        }
        if (ctx.check_history) {
            html += '<div class="decision-context">查验记录：' + ctx.check_history + '</div>';
        }
        if (ctx.discussion_summary) {
            html += '<div class="decision-context">讨论总结：' + ctx.discussion_summary + '</div>';
        }
    }

    html += '<div class="decision-options">';
    const targets = ctx.valid_targets || [];
    targets.forEach(function (t) {
        html += '<button class="decision-btn target-btn" data-target="' + t.id + '">' + t.label + '</button>';
    });
    if (allowSkip) {
        html += '<button class="decision-btn skip" data-target="0">弃票 / 放弃</button>';
    }
    html += '</div>';

    html += '<div style="margin-top:12px;">' +
        '<button class="decision-btn primary submit-targets" data-did="' + did + '" disabled>确认选择</button>' +
        '</div>';

    return html;
}

function renderFreeSpeech(did, ctx, title, showContext) {
    let html = '<div class="decision-title">' + title + '</div>';

    if (showContext !== false) {
        if (ctx.death_summary) {
            html += '<div class="decision-context">' + ctx.death_summary + '</div>';
        }
        if (ctx.private_info) {
            html += '<div class="decision-context">' + ctx.private_info + '</div>';
        }
        if (ctx.allies && ctx.allies.length) {
            html += '<div class="decision-context">🐺 你的狼队友：' + ctx.allies.join('、') + '</div>';
        }
        if (ctx.discussion_history) {
            html += '<div class="decision-context">已有讨论：\n' + ctx.discussion_history + '</div>';
        }
        if (ctx.suspicions && ctx.suspicions !== '（暂无怀疑对象）') {
            html += '<div class="decision-context">怀疑对象：' + ctx.suspicions + '</div>';
        }
    }

    html += '<textarea class="decision-textarea" id="speech-input" placeholder="输入你的发言..."></textarea>';
    html += '<button class="decision-btn primary" data-did="' + did + '" id="submit-speech">提交发言</button>';
    return html;
}

function renderYesNo(did, ctx, title) {
    let html = '<div class="decision-title">' + title + '</div>';

    if (ctx.private_info) {
        html += '<div class="decision-context">' + ctx.private_info + '</div>';
    }
    if (ctx.death_summary) {
        html += '<div class="decision-context">' + ctx.death_summary + '</div>';
    }
    if (ctx.current_candidates && ctx.current_candidates.length) {
        html += '<div class="decision-context">已报名参选：' + ctx.current_candidates.map(function(c){return c+'号';}).join('、') + '</div>';
    }

    html += '<div class="decision-options">' +
        '<button class="decision-btn primary" data-did="' + did + '" data-value="true">参选</button>' +
        '<button class="decision-btn skip" data-did="' + did + '" data-value="false">不参选</button>' +
        '</div>';
    return html;
}

function renderWitchDecision(did, ctx) {
    let html = '<div class="decision-title">🧪 女巫用药决策</div>';

    html += '<div class="decision-context">';
    html += '狼人击杀目标：' + ctx.attacked_label + '\n';
    html += '解药：' + (ctx.antidote_available ? '可用' : '已用') + ' | 毒药：' + (ctx.poison_available ? '可用' : '已用');
    if (ctx.is_self_attacked) {
        html += '\n⚠️ 狼人击杀目标是你自己！可以使用解药自救。';
    }
    html += '</div>';

    html += '<div class="decision-options">';
    if (ctx.antidote_available) {
        html += '<button class="decision-btn primary" data-did="' + did + '" data-value=\'{"action":"save"}\'>💚 使用解药</button>';
    }
    if (ctx.poison_available) {
        html += '<button class="decision-btn danger poison-select-btn">💀 使用毒药...</button>';
        html += '<div class="poison-targets" style="display:none;margin-top:8px;">';
        (ctx.alive_players || []).forEach(function(p) {
            html += '<button class="decision-btn danger poison-target-btn" data-target="' + p.id + '" data-did="' + did + '" data-value=\'{"action":"poison","target":' + p.id + '}\'>毒杀 ' + p.label + '</button>';
        });
        html += '</div>';
    }
    html += '<button class="decision-btn skip" data-did="' + did + '" data-value=\'{"action":"none"}\'>不使用药水</button>';
    html += '</div>';

    return html;
}

// ── Selection Helpers ───────────────────────────────

function applySelectedInline(btn) {
    var s = btn.style;
    s.setProperty('background', 'rgba(74, 222, 128, 0.18)', 'important');
    s.setProperty('border-color', '#4ade80', 'important');
    s.setProperty('color', '#ffffff', 'important');
    s.setProperty('box-shadow', '0 0 20px rgba(74,222,128,0.3), inset 0 0 10px rgba(74,222,128,0.1)', 'important');
    s.setProperty('transform', 'scale(1.03)', 'important');
    s.setProperty('font-weight', '700', 'important');
    btn.classList.add('selected');
}

function removeSelectedInline(btn) {
    var s = btn.style;
    s.removeProperty('background');
    s.removeProperty('border-color');
    s.removeProperty('color');
    s.removeProperty('box-shadow');
    s.removeProperty('transform');
    s.removeProperty('font-weight');
    btn.classList.remove('selected');
}

// ── Delegated Click Handler ─────────────────────────

function setupDecisionZoneDelegation() {
    var zone = document.getElementById('decision-zone');
    zone.addEventListener('click', function (e) {
        var targetBtn = e.target.closest('.target-btn, .decision-btn.skip[data-target]');
        if (targetBtn) {
            var tid = parseInt(targetBtn.getAttribute('data-target'));
            var idx = selectedTargets.indexOf(tid);
            if (idx >= 0) {
                selectedTargets.splice(idx, 1);
                removeSelectedInline(targetBtn);
            } else {
                selectedTargets = [tid];
                document.querySelectorAll('.target-btn, .decision-btn.skip[data-target]').forEach(function(b) { removeSelectedInline(b); });
                applySelectedInline(targetBtn);
            }
            var submitBtn = document.querySelector('.submit-targets');
            if (submitBtn) {
                submitBtn.disabled = (selectedTargets.length === 0);
            }
            return;
        }

        var submitBtn = e.target.closest('.submit-targets');
        if (submitBtn && selectedTargets.length > 0) {
            submitDecision(submitBtn.getAttribute('data-did'), selectedTargets[0] === 0 ? null : selectedTargets[0]);
            return;
        }
    });
}

// ── Decision Event Binding ──────────────────────────

function bindDecisionEvents(did, dtype, ctx) {
    // Free speech submit
    var submitSpeech = document.getElementById('submit-speech');
    if (submitSpeech) {
        submitSpeech.addEventListener('click', function () {
            const text = document.getElementById('speech-input').value.trim();
            if (text) {
                submitDecision(did, text);
            }
        });
    }

    // Speech input: Enter to submit (Shift+Enter for newline)
    var speechInput = document.getElementById('speech-input');
    if (speechInput) {
        speechInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const text = this.value.trim();
                if (text) {
                    submitDecision(did, text);
                }
            }
        });
        // Auto-focus
        speechInput.focus();
    }

    // Yes/No buttons
    document.querySelectorAll('[data-value="true"], [data-value="false"]').forEach(function (btn) {
        if (btn.classList.contains('poison-target-btn') || btn.classList.contains('poison-select-btn')) return;
        btn.addEventListener('click', function () {
            const val = this.getAttribute('data-value');
            submitDecision(did, val === 'true');
        });
    });

    // Witch poison select button
    var poisonSelect = document.querySelector('.poison-select-btn');
    if (poisonSelect) {
        poisonSelect.addEventListener('click', function () {
            const targets = document.querySelector('.poison-targets');
            if (targets) targets.style.display = targets.style.display === 'none' ? '' : 'none';
        });
    }

    // Witch poison target buttons
    document.querySelectorAll('.poison-target-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const val = this.getAttribute('data-value');
            submitDecision(did, JSON.parse(val));
        });
    });

    // Witch save / none buttons
    document.querySelectorAll('[data-value*="action"]').forEach(function (btn) {
        if (btn.classList.contains('poison-target-btn')) return;
        btn.addEventListener('click', function () {
            const val = this.getAttribute('data-value');
            submitDecision(did, JSON.parse(val));
        });
    });
}

function clearSelection() {
    selectedTargets = [];
    document.querySelectorAll('.target-btn, .decision-btn.skip[data-target]').forEach(function(b){ removeSelectedInline(b); });
}

// ── Decision Submission ─────────────────────────────

async function submitDecision(decisionId, value) {
    const form = new FormData();
    form.append('decision_id', decisionId);
    form.append('value', JSON.stringify(value));
    await fetch('/api/decision', { method: 'POST', body: form });
    const zone = document.getElementById('decision-zone');
    zone.style.display = 'none';
    zone.innerHTML = '<p style="color:var(--text-muted);padding:12px;text-align:center;">✔️ 决策已提交，等待游戏继续...</p>';
    clearSelection();
}

// ── Role Overlay ────────────────────────────────────

function showRoleOverlay(info) {
    const overlay = document.getElementById('role-overlay');
    overlay.style.display = '';
    let html = '<p>你的编号：<strong>玩家' + info.player_id + '号</strong></p>';
    html += '<p>你的身份：<strong style="color:var(--gold);font-size:1.2em;">' + info.role + '</strong></p>';
    html += '<p>你的阵营：' + info.team + '</p>';
    html += '<p>你的能力：' + info.ability + '</p>';
    if (info.allies && info.allies.length) {
        html += '<p class="allies">🐺 狼队友：' + info.allies.join('、') + '</p>';
    }
    document.getElementById('role-info-content').innerHTML = html;
}

function dismissRoleInfo() {
    document.getElementById('role-overlay').style.display = 'none';
}

// ── Game Over ───────────────────────────────────────

function showGameOver(state) {
    if (document.getElementById('game-over-overlay')) return;

    const isGoodWin = state.events && state.events.length &&
        state.events[state.events.length - 1].text.includes('好人');

    let html = '<div class="game-over-overlay ' + (isGoodWin ? 'good-wins' : 'evil-wins') + '">';
    html += '<h2>' + (isGoodWin ? '🎉 好人阵营胜利！' : '🐺 狼人阵营胜利！') + '</h2>';
    html += '<div class="final-players">';
    state.players.forEach(function(p) {
        html += '<div class="final-player">' +
            '<strong>' + p.name + '</strong><br>' +
            p.role + ' — ' + (p.is_alive ? '生存' : '💀死亡') +
            '</div>';
    });
    html += '</div>';
    html += '<p style="margin-top:20px"><a href="/" style="color:var(--gold);text-decoration:none;font-weight:600;font-size:1.05em;">🔙 返回首页再来一局</a></p>';
    html += '</div>';

    const overlay = document.createElement('div');
    overlay.id = 'game-over-overlay';
    overlay.innerHTML = html;
    document.body.appendChild(overlay);
}

// ── Kickoff ─────────────────────────────────────────
setupDecisionZoneDelegation();
connectSSE();
