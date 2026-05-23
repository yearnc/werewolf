"""GameRunner — bridges the async game engine to the web layer via SSE + Future-based decision awaiting."""

import asyncio
import json
import uuid

from config import Config
from game import Game
from human_player import WebHumanPlayer
from role import ROLE_ABILITY, ROLE_DISPLAY, Role, Team, get_team


class DecisionAwaiter:
    """Manages pending human-player decisions and an SSE state queue."""

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}
        self._state_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._last_state: dict = {}
        self._current_pending_state: dict | None = None

    def set_last_state(self, state: dict) -> None:
        """Store the last full game state for merging into waiting states."""
        self._last_state = dict(state)

    async def push_state(self, state: dict) -> None:
        await self._state_queue.put(state)

    def state_queue_iter(self):
        """Return an async iterator over the state queue."""
        return self._queue_iter()

    async def _queue_iter(self):
        while True:
            state = await self._state_queue.get()
            yield state

    def get_pending_decision(self) -> dict | None:
        """Return the current pending decision state if any, for SSE reconnect recovery."""
        return self._current_pending_state

    async def wait(self, decision_type: str, context: dict):
        """Called by WebHumanPlayer. Pushes a 'waiting' state and blocks until resolved."""
        decision_id = str(uuid.uuid4())[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[decision_id] = future

        # Build a full state snapshot so the frontend doesn't crash on missing fields.
        # Merge the last known game state with the decision prompt.
        pending_state = {
            **self._last_state,
            "waiting_for_human": True,
            "decision_id": decision_id,
            "decision_type": decision_type,
            "decision_context": context,
        }
        self._current_pending_state = pending_state
        await self._state_queue.put(pending_state)

        try:
            result = await future
            return result
        finally:
            self._pending.pop(decision_id, None)
            self._current_pending_state = None

    def resolve(self, decision_id: str, value):
        """Called by the web API when the user submits a decision."""
        future = self._pending.get(decision_id)
        if future and not future.done():
            future.set_result(value)
            return True
        return False


class GameRunner:
    """Owns the game lifecycle and manages background execution."""

    def __init__(self, config: Config):
        self.config = config
        self.awaiter = DecisionAwaiter()
        self._game: Game | None = None
        self._task: asyncio.Task | None = None
        self._current_state: dict = {}
        self._runner_generation: int = 0

    @property
    def game(self) -> Game | None:
        return self._game

    def current_state(self) -> dict:
        return self._current_state

    def _on_state(self, state: dict) -> None:
        """Callback from Game._emit_state() or direct state push."""
        self._runner_generation += 1
        state["generation"] = self._runner_generation
        self._current_state = state
        # Keep awaiter in sync so waiting states carry the full game state
        self.awaiter.set_last_state(state)
        # Push to SSE queue (non-blocking via put_nowait)
        try:
            self.awaiter._state_queue.put_nowait(state)
        except asyncio.QueueFull:
            pass

    async def start_game(self, mode: str) -> None:
        """Start a game in 'ai' or 'human' mode as a background task."""
        self._game = Game(self.config)
        self._game.set_state_callback(self._on_state)

        if mode == "human":
            self._task = asyncio.create_task(self._run_human_mode())
        else:
            self._task = asyncio.create_task(self._run_ai_mode())

    async def _run_ai_mode(self) -> None:
        try:
            await self._game.run_ai_referee()
        except Exception as e:
            import logging
            import traceback
            logging.getLogger("werewolf").error(f"AI 裁判模式异常：{e}\n{traceback.format_exc()}")
        finally:
            # Push final state
            if self._current_state:
                self._on_state(self._current_state)

    async def _run_human_mode(self) -> None:
        try:
            # Inject WebHumanPlayer with our awaiter
            self._game.setup_human_mode(
                human_player_class=lambda player_id, role, config: WebHumanPlayer(
                    player_id, role, config, self.awaiter
                )
            )

            human = self._game.players[self._game._human_player_id - 1]
            role_name = ROLE_DISPLAY[human.role]
            team = "狼人阵营" if get_team(human.role) == Team.EVIL else "好人阵营"
            ability = ROLE_ABILITY[human.role]

            # Show human their role via a special state
            self._on_state({
                **self._current_state,
                "human_role_info": {
                    "player_id": human.player_id,
                    "role": role_name,
                    "team": team,
                    "ability": ability,
                    "allies": [f"玩家{a}号" for a in human.memory.werewolf_allies] if human.role == Role.WEREWOLF else [],
                }
            })

            await self._game.run_human_player_mode()
        except Exception as e:
            import logging
            import traceback
            logging.getLogger("werewolf").error(f"人类玩家模式异常：{e}\n{traceback.format_exc()}")
        finally:
            if self._current_state:
                self._on_state(self._current_state)

    def submit_decision(self, decision_id: str, value) -> bool:
        """Submit a human player's decision. Returns True if the decision was pending."""
        return self.awaiter.resolve(decision_id, value)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
