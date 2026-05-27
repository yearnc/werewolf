"""Game engine — state machine, night/day logic, win detection."""

from __future__ import annotations

import asyncio
import random
import re
from collections import Counter
from enum import Enum
from typing import Callable, Optional

from ai_player import AIPlayer
from config import Config
from human_player import HumanPlayer
from llm_client import LLMClient
from memory import Speech, VoteRecord
from role import DEFAULT_ROLES, ROLE_ABILITY, ROLE_DISPLAY, Role, Team, get_team
from utils import logger

_ROLE_TAG_PATTERN = re.compile(r"\((?:狼人|预言家|女巫|猎人|村民)\)")

# Event types that must NOT be shown to human players (private info)
_PRIVATE_EVENT_TYPES = {"wolf_discuss", "seer_check", "witch_action", "wolf_action"}


class GamePhase(Enum):
    SETUP = "setup"
    NIGHT = "night"
    DAY_ANNOUNCE = "day_announce"
    SHERIFF_ELECTION = "sheriff_election"
    SPEAKING = "speaking"
    VOTING = "voting"
    GAME_OVER = "game_over"


class Game:
    def __init__(self, config: Config):
        self.config = config
        self.players: list = []
        self.phase = GamePhase.SETUP
        self.day = 0
        self.night = 0
        self.sheriff_id: int | None = None
        self._sheriff_election_done = False
        self._sheriff_election_summary: str = ""
        self._sheriff_log: list[str] = []
        self._wolf_discussion_history: list[str] = []
        self._death_log: list[str] = []
        self.speech_order: list[int] = []
        self._night_kill_target: int | None = None
        self._witch_saved: bool = False
        self._witch_poisoned: int | None = None
        self._witch_saved_target: int | None = None
        self._witch_save_night: int = 0
        self._witch_poison_night: int = 0
        self._wolf_kill_log: list[str] = []
        self._tonight_deaths: list[int] = []
        self._speech_cache: str = ""
        self._speech_cache_version: int = -1
        self._vote_cache: str = ""
        self._vote_cache_version: int = -1
        self._vote_generation: int = 0
        self._human_player_mode: bool = False
        self._human_player_id: int | None = None
        self._speech_generation: int = 0
        self._state_callback: Callable[[dict], None] | None = None
        self._event_log: list[dict] = []
        self._state_generation: int = 0

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Assign roles and create AI players, each with its own LLM client."""
        roles = list(DEFAULT_ROLES)
        random.shuffle(roles)

        for i, role in enumerate(roles):
            pid = i + 1
            api_key = self.config.get_key_for_player(pid)
            llm = LLMClient(self.config, api_key)
            player = AIPlayer(
                player_id=pid,
                role=role,
                config=self.config,
                llm_client=llm,
            )
            self.players.append(player)

        # Tell werewolves who their allies are
        werewolf_ids = [p.player_id for p in self.players if p.role == Role.WEREWOLF]
        for p in self.players:
            if p.role == Role.WEREWOLF:
                allies = [wid for wid in werewolf_ids if wid != p.player_id]
                p.memory.werewolf_allies = allies

        self.phase = GamePhase.SETUP
        self.night = 0
        self.day = 0
        self._sheriff_election_done = False
        self._sheriff_election_summary = ""
        self._death_log = []
        self._wolf_kill_log = []
        self._wolf_discussion_history = []
        self._sheriff_log = []
        self.sheriff_id = None
        logger.info(f"游戏初始化完成，{len(self.players)}名玩家已就位。")
        self._add_event("system", f"游戏初始化完成，{len(self.players)}名玩家已就位。")
        self._emit_state()

    def setup_human_mode(self, human_player_class=None) -> None:
        """Set up a game with one human player and 8 AI players."""
        if human_player_class is None:
            human_player_class = HumanPlayer
        self._human_player_mode = True

        human_role = random.choice(list(Role))

        ai_roles = list(DEFAULT_ROLES)
        for i, r in enumerate(ai_roles):
            if r == human_role:
                ai_roles.pop(i)
                break
        random.shuffle(ai_roles)

        human_pid = random.randint(1, 9)
        self._human_player_id = human_pid

        ai_idx = 0
        for pid in range(1, 10):
            if pid == human_pid:
                player = human_player_class(player_id=pid, role=human_role, config=self.config)
            else:
                role = ai_roles[ai_idx]
                ai_idx += 1
                api_key = self.config.get_key_for_player(pid)
                llm = LLMClient(self.config, api_key)
                player = AIPlayer(player_id=pid, role=role, config=self.config, llm_client=llm)
            self.players.append(player)

        werewolf_ids = [p.player_id for p in self.players if p.role == Role.WEREWOLF]
        for p in self.players:
            if p.role == Role.WEREWOLF:
                allies = [wid for wid in werewolf_ids if wid != p.player_id]
                p.memory.werewolf_allies = allies

        self.phase = GamePhase.SETUP
        self.night = 0
        self.day = 0
        self._sheriff_election_done = False
        self._sheriff_election_summary = ""
        self._death_log = []
        self._wolf_kill_log = []
        self._wolf_discussion_history = []
        self._sheriff_log = []
        self.sheriff_id = None
        logger.info(f"游戏初始化完成，{len(self.players)}名玩家已就位。")
        self._add_event("system", f"游戏初始化完成，{len(self.players)}名玩家已就位。")
        self._emit_state()

    # ------------------------------------------------------------------
    # Night phase
    # ------------------------------------------------------------------

    async def do_night_phase(self) -> None:
        """Execute all night actions."""
        self.phase = GamePhase.NIGHT
        self.night += 1
        self._night_kill_target = None
        self._witch_saved = False
        self._witch_poisoned = None
        self._tonight_deaths = []

        alive = self.alive_ids()
        if not alive:
            return

        # Build shared context for night LLM calls
        recent_speeches = self._all_recent_speeches()
        recent_votes = self._all_recent_votes()
        death_summary = self._death_summary()

        # Build wolf kill history for wolf-only context
        if self._wolf_kill_log:
            wolf_kill_history = "（私密信息）你们的击杀记录：\n" + "\n".join(f"  {entry}" for entry in self._wolf_kill_log)
        else:
            wolf_kill_history = ""

        # Build past discussion summary for wolf context
        if self._wolf_discussion_history:
            past_discussions = "## 往夜讨论回顾\n" + "\n---\n".join(self._wolf_discussion_history)
        else:
            past_discussions = ""

        logger.info(f"\n{'='*50}")
        logger.info(f"🌙 第{self.night}夜 降临")
        logger.info(f"{'='*50}")
        self._add_event("phase", f"🌙 第{self.night}夜 降临")
        self._emit_state()

        # 1. Werewolves discuss then pick kill target
        werewolves = [p for p in self.players if p.role == Role.WEREWOLF and p.is_alive]
        if werewolves:
            discussion_summary = "（独狼，无需讨论）"
            if len(werewolves) > 1:
                # --- Wolf discussion rounds (sequential within each round) ---
                discussion_log: list[str] = []
                for rnd in range(1, 2):  # 1 round of discussion
                    logger.debug(f"\n🐺 狼人讨论...")
                    self._add_event("wolf_discuss", "🐺 狼人开始讨论击杀目标...")
                    self._emit_state()
                    for w in werewolves:
                        speech = await w.wolf_discussion_speak(
                            self.night, alive, recent_speeches, recent_votes,
                            "\n".join(discussion_log), rnd, 1, death_summary,
                            wolf_kill_history=wolf_kill_history,
                            past_discussions=past_discussions,
                        )
                        discussion_log.append(f"玩家{w.player_id}号：{speech}")
                        logger.debug(f"🐺 玩家{w.player_id}号（狼人）：{speech}")
                        self._add_event("wolf_discuss", f"🐺 玩家{w.player_id}号（狼人）：{speech}", w.player_id)
                        self._emit_state()

                discussion_summary = "\n".join(discussion_log)
                # Save discussion for future nights
                self._wolf_discussion_history.append(f"第{self.night}夜讨论：\n{discussion_summary}")

            # --- Wolf kill voting ---
            if len(werewolves) > 1:
                logger.debug("\n🐺 狼人讨论结束，各自投票决定击杀目标...")
            else:
                logger.debug("🐺 独狼行动，直接选择击杀目标...")
            kill_votes: list[int] = []
            wolf_vote_details: list[tuple[int, int]] = []  # (voter_id, target_id)
            tasks = [
                w.werewolf_kill_decision(
                    self.night, alive, recent_speeches, recent_votes,
                    discussion_summary, death_summary,
                    wolf_kill_history=wolf_kill_history,
                )
                for w in werewolves
            ]
            results = await asyncio.gather(*tasks)
            for w, target in zip(werewolves, results):
                if target is not None:
                    kill_votes.append(target)
                    wolf_vote_details.append((w.player_id, target))

            if kill_votes:
                # Majority vote among werewolves
                counter = Counter(kill_votes)
                most_common = counter.most_common()
                if len(most_common) == 1 or most_common[0][1] > len(kill_votes) // 2:
                    self._night_kill_target = most_common[0][0]
                else:
                    # Tie — pick random among top choices
                    max_count = most_common[0][1]
                    tied = [t for t, c in most_common if c == max_count]
                    self._night_kill_target = random.choice(tied)

            kill_target_role = ROLE_DISPLAY[self._role_of(self._night_kill_target)] if self._night_kill_target else "?"
            logger.debug(f"🔪 狼人今晚选择了击杀 玩家{self._night_kill_target}号({kill_target_role})")
            logger.debug(f"狼人击杀投票：{kill_votes}，最终目标：{self._night_kill_target}号")

            # Show kill result to human werewolf
            if self._human_player_mode and self._human_player_id in [w.player_id for w in werewolves]:
                logger.info(f"\n🐺 狼人投票结果：")
                for v, t in wolf_vote_details:
                    logger.info(f"  {v}号 → {t}号")
                logger.info(f"🔪 今晚击杀目标：玩家{self._night_kill_target}号({kill_target_role})")

            self._add_event("wolf_action", f"🐺 狼人行动完毕，击杀目标：玩家{self._night_kill_target}号")
            self._emit_state()

        # 2. Seer checks
        seer = self._find_alive(Role.SEER)
        if seer:
            logger.debug("预言家请睁眼，选择要查验的玩家...")
            target = await seer.seer_check_decision(
                self.night, alive, recent_speeches, recent_votes, death_summary,
            )
            if target is not None:
                target_role = self._role_of(target)
                is_werewolf = target_role == Role.WEREWOLF
                seer.memory.add_check_result(target, is_werewolf, self.night)
                result_text = "狼人" if is_werewolf else "好人"
                if seer.player_id == self._human_player_id:
                    logger.info(f"🔮 你查验了 玩家{target}号 → {result_text}")
                else:
                    logger.debug(f"🔮 预言家{seer.player_id}号查验了 玩家{target}号 → {result_text}")
                self._add_event("seer_check", f"🔮 预言家查验了 玩家{target}号 → {result_text}")
                self._emit_state()

        # 3. Witch decides (if alive and has potions)
        witch = self._find_alive(Role.WITCH)
        if witch and (not witch.memory.antidote_used or not witch.memory.poison_used):
            logger.debug("女巫请睁眼，决定是否使用药水...")
            action, target = await witch.witch_night_decision(
                self.night, alive, self._night_kill_target,
                recent_speeches, recent_votes, death_summary,
            )
            if action == "save" and not witch.memory.antidote_used:
                witch.memory.antidote_used = True
                self._witch_saved = True
                self._witch_saved_target = self._night_kill_target
                self._witch_save_night = self.night
                logger.debug(f"女巫使用了解药，拯救了玩家{self._night_kill_target}号")
                self._add_event("witch_action", f"🧪 女巫使用了解药，拯救了玩家{self._night_kill_target}号")
            elif action == "poison" and target is not None and not witch.memory.poison_used:
                witch.memory.poison_used = True
                self._witch_poisoned = target
                self._witch_poison_night = self.night
                logger.debug(f"女巫使用了毒药，毒杀了玩家{target}号")
                self._add_event("witch_action", f"🧪 女巫使用了毒药，毒杀了玩家{target}号")
            else:
                self._add_event("witch_action", "🧪 女巫选择不使用药水")
            self._emit_state()

        # 4. Resolve deaths
        self._tonight_deaths = []
        if self._night_kill_target and not self._witch_saved:
            self._tonight_deaths.append(self._night_kill_target)
        if self._witch_poisoned and self._witch_poisoned != self._night_kill_target:
            self._tonight_deaths.append(self._witch_poisoned)

        # Kill players
        for pid in self._tonight_deaths:
            self.players[pid - 1].kill()

        # Log deaths (public view — night deaths don't reveal cause)
        if self._night_kill_target and not self._witch_saved:
            self._death_log.append(f"第{self.night}夜：玩家{self._night_kill_target}号死亡")
        if self._witch_poisoned and self._witch_poisoned != self._night_kill_target:
            self._death_log.append(f"第{self.night}夜：玩家{self._witch_poisoned}号死亡")

        # Log wolf kill result (private — only wolves see this)
        if self._night_kill_target is not None:
            if self._witch_saved:
                self._wolf_kill_log.append(f"第{self.night}夜你们刀了 玩家{self._night_kill_target}号，但被女巫救活")
            else:
                self._wolf_kill_log.append(f"第{self.night}夜你们刀了 玩家{self._night_kill_target}号，已死亡")

        # Record deaths in all memories
        for p in self.players:
            for pid in self._tonight_deaths:
                p.memory.add_death(pid, self.night)

        # 5. Hunter revenge shot (only if killed by werewolves, not by poison)
        kill_target = self._night_kill_target if not self._witch_saved else None
        if kill_target and self._role_of(kill_target) == Role.HUNTER:
            await self._hunter_shot(kill_target, "狼人击杀")

        # 6. Sheriff death: pass the badge
        for pid in self._tonight_deaths:
            await self._handle_sheriff_death(pid)

        self._emit_state()

        # 7. Check win condition before transitioning to day
        if self._check_win():
            return

        self.phase = GamePhase.DAY_ANNOUNCE
        self._emit_state()

    # ------------------------------------------------------------------
    # Day phase
    # ------------------------------------------------------------------

    def do_day_announcement(self) -> None:
        """Announce night results."""
        self.day += 1
        alive = self.alive_ids()
        alive_str = ", ".join(f"{i}号({ROLE_DISPLAY[self._role_of(i)]})" for i in alive)

        logger.info(f"\n{'='*50}")
        logger.info(f"☀️ 第{self.day}天 白天")
        logger.info(f"{'='*50}")

        if self._tonight_deaths:
            for pid in self._tonight_deaths:
                role_name = ROLE_DISPLAY[self._role_of(pid)]
                logger.info(self._public(f"💀 昨晚 玩家{pid}号({role_name}) 死亡"))
                self._add_event("death", f"💀 昨晚 玩家{pid}号 死亡", pid)
        else:
            logger.info("✨ 昨晚是平安夜，无人死亡")
            self._add_event("peace", "✨ 昨晚是平安夜，无人死亡")

        logger.info(self._public(f"存活玩家（{len(alive)}人）：{alive_str}"))
        self._emit_state()

        if self._check_win():
            return

        # Day 1 after first night: go to sheriff election
        if self.day == 1 and not self._sheriff_election_done:
            self.phase = GamePhase.SHERIFF_ELECTION
            self._add_event("phase", "🎖️ 进入警长竞选阶段")
            self._emit_state()
            return

        # Determine speech order: alive players sorted by ID, sheriff last
        self.speech_order = self._build_speech_order(alive)
        self.phase = GamePhase.SPEAKING
        self._emit_state()

    async def do_sheriff_election(self) -> None:
        """Run sheriff election: candidacy → campaign speeches → vote."""
        alive = self.alive_ids()
        logger.info(f"\n{'='*50}")
        logger.info("🎖️ 警长竞选")
        logger.info(f"{'='*50}")
        self._add_event("phase", "🎖️ 警长竞选开始")

        # Step 1: Each player decides whether to run
        logger.info("\n--- 报名上警 ---")
        candidates: list[int] = []
        voters: list[int] = []
        death_summary = self._death_summary()
        for pid in sorted(alive):
            player = self.players[pid - 1]
            private = self._private_info(player)
            decision = await player.sheriff_candidacy_decision(alive, death_summary, private, list(candidates))
            if decision:
                candidates.append(pid)
                logger.info(self._public(f"🙋 玩家{pid}号({ROLE_DISPLAY[player.role]})：参加竞选"))
            else:
                voters.append(pid)
                logger.info(self._public(f"✋ 玩家{pid}号({ROLE_DISPLAY[player.role]})：不参加竞选"))

        self._add_event("election", f"警长参选报名：{'、'.join(f'{c}号' for c in candidates)}参选，{'、'.join(f'{v}号' for v in voters)}投票")
        self._emit_state()

        # Edge case: no candidates → pick random wolf-free alive player
        if not candidates:
            self.sheriff_id = random.choice(alive) if alive else None
            if self.sheriff_id:
                logger.info(f"无人参选，随机指定 玩家{self.sheriff_id}号 为警长")
            self._sheriff_election_done = True
            self.speech_order = self._build_speech_order(alive)
            self.phase = GamePhase.SPEAKING
            return

        # Edge case: no voters → randomly assign sheriff (candidates can't vote for sheriff)
        if not voters:
            self.sheriff_id = random.choice(candidates)
            self._sheriff_election_done = True
            self.speech_order = self._build_speech_order(alive)
            self.phase = GamePhase.SPEAKING
            return

        # Step 2: Candidates give campaign speeches
        logger.info("\n--- 竞选发言 ---")
        campaign_speeches: dict[int, str] = {}
        for pid in sorted(candidates):
            player = self.players[pid - 1]
            private = self._private_info(player)
            speech = await player.generate_campaign_speech(alive, death_summary, private)
            self._speech_generation += 1
            campaign_speeches[pid] = speech
            logger.info(self._public(f"📢 玩家{pid}号({ROLE_DISPLAY[player.role]})：{speech}"))
            self._add_event("campaign_speech", f"📢 玩家{pid}号（竞选警长）：{speech}", pid)
            self._emit_state()

        # Store campaign speeches for later vote context
        campaign_text = "\n".join(f"玩家{pid}号：{s}" for pid, s in campaign_speeches.items())
        self._emit_state()

        # Step 2.5: Candidates may withdraw (退水)
        if len(candidates) > 1:
            logger.info("\n--- 退水环节 ---")
            for pid in sorted(candidates):
                if len(candidates) <= 1:
                    break
                player = self.players[pid - 1]
                private = self._private_info(player)
                withdraw = await player.sheriff_withdraw_decision(
                    list(candidates), campaign_speeches, private, death_summary,
                )
                if withdraw:
                    candidates.remove(pid)
                    voters.append(pid)
                    logger.info(self._public(f"🏳️ 玩家{pid}号({ROLE_DISPLAY[player.role]})：退水"))
                    self._add_event("election", f"🏳️ 玩家{pid}号 退水，退出警长竞选")
                    self._emit_state()

        # After withdrawals: handle edge cases
        if not candidates:
            self.sheriff_id = random.choice(alive) if alive else None
            if self.sheriff_id:
                logger.info(f"所有候选人退水，随机指定 玩家{self.sheriff_id}号 为警长")
            self._sheriff_election_done = True
            self.speech_order = self._build_speech_order(alive)
            self.phase = GamePhase.SPEAKING
            return

        if len(candidates) == 1:
            self.sheriff_id = candidates[0]
            sheriff_role = ROLE_DISPLAY[self._role_of(self.sheriff_id)]
            logger.info(self._public(f"🎖️ 仅有 玩家{self.sheriff_id}号({sheriff_role}) 留在警上，自动当选警长！"))
            self._add_event("election", f"🎖️ 其他候选人退水，玩家{self.sheriff_id}号({sheriff_role}) 自动当选警长！")
            self._sheriff_log.append(f"第{self.day}天：玩家{self.sheriff_id}号自动当选警长（退水）")
            self._sheriff_election_done = True
            self.speech_order = self._build_speech_order(alive)
            self.phase = GamePhase.SPEAKING
            self._emit_state()
            return

        # Re-check voters after withdrawals
        if not voters:
            self.sheriff_id = random.choice(candidates)
            self._sheriff_election_done = True
            self.speech_order = self._build_speech_order(alive)
            self.phase = GamePhase.SPEAKING
            return

        # Step 3: Non-candidates vote for sheriff
        logger.info("\n--- 警长投票 ---")
        tasks = []
        for pid in voters:
            player = self.players[pid - 1]
            private = self._private_info(player)
            tasks.append(player.sheriff_vote_decision(candidates, campaign_text, private, death_summary))

        results = await asyncio.gather(*tasks)

        vote_tally: Counter[int] = Counter()
        vote_events: list[str] = []
        for voter_id, target in zip(voters, results):
            if target is not None:
                vote_tally[target] += 1
                logger.info(f"🗳️ 玩家{voter_id}号 → 投票警长 玩家{target}号")
                vote_events.append(f"🗳️ 玩家{voter_id}号 → 警长 玩家{target}号")
                self.players[voter_id - 1].memory.add_sheriff_vote(
                    VoteRecord(voter_id, target, self.day)
                )
            else:
                vote_events.append(f"🚫 玩家{voter_id}号 警长投票弃权")
        self._vote_generation += 1

        # Emit individual sheriff votes as events
        for evt in vote_events:
            self._add_event("vote", evt)

        if not vote_tally:
            self.sheriff_id = random.choice(candidates)
            logger.info(f"警长投票无有效结果，随机指定 玩家{self.sheriff_id}号 为警长")
        else:
            most_common = vote_tally.most_common()
            if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
                max_votes = most_common[0][1]
                tied = [pid for pid, count in most_common if count == max_votes]
                self.sheriff_id = random.choice(tied)
                logger.info(f"警长投票平票，随机从 {'、'.join(f'{t}号' for t in tied)} 中选择")
            else:
                self.sheriff_id = most_common[0][0]

        sheriff_role = ROLE_DISPLAY[self._role_of(self.sheriff_id)]
        logger.info(self._public(f"\n🎖️ 玩家{self.sheriff_id}号({sheriff_role}) 当选警长！拥有1.5票且最后发言。"))

        # Build vote tally summary for event log (include who voted for whom)
        tally_lines = []
        for pid, count in vote_tally.most_common():
            supporters = [f"{v}号" for v, t in zip(voters, results) if t == pid]
            tally_lines.append(f"玩家{pid}号 {count}票 ← {', '.join(supporters)}")
        self._add_event("election", f"📊 警长投票结果：{'；'.join(tally_lines)}")

        # Record sheriff election in history
        self._sheriff_log.append(f"第{self.day}天：玩家{self.sheriff_id}号当选警长")

        # Build election summary for inclusion in future context
        non_candidates = [pid for pid in alive if pid not in candidates]
        summary_parts = ["警长竞选回顾："]
        summary_parts.append(f"- 报名参选（{len(candidates)}人，失去警长投票权）：{'、'.join(f'{c}号' for c in candidates)}")
        summary_parts.append(f"- 未参选（{len(non_candidates)}人，拥有警长投票权）：{'、'.join(f'{nc}号' for nc in non_candidates)}")
        summary_parts.append(f"- 竞选发言：")
        for pid, s in campaign_speeches.items():
            summary_parts.append(f"  {pid}号：{s}")
        self._sheriff_election_summary = "\n".join(summary_parts)

        self._sheriff_election_done = True

        # Proceed to speaking phase
        self.speech_order = self._build_speech_order(alive)
        self.phase = GamePhase.SPEAKING
        # In human mode, hide the sheriff's role unless the human player IS the sheriff
        if self._human_player_mode and self.sheriff_id != self._human_player_id:
            self._add_event("election", f"🎖️ 玩家{self.sheriff_id}号 当选警长！")
        else:
            sheriff_role = ROLE_DISPLAY[self._role_of(self.sheriff_id)] if self.sheriff_id else "?"
            self._add_event("election", f"🎖️ 玩家{self.sheriff_id}号({sheriff_role}) 当选警长！")
        self._emit_state()

    async def do_speaking_phase(self) -> None:
        """Each alive player gives a speech. Sheriff speaks last."""
        alive = self.alive_ids()
        if not self.speech_order:
            self.speech_order = self._build_speech_order(alive)

        current_order = [i for i in self.speech_order if i in alive]

        logger.info(f"\n--- 发言环节（第{self.day}天）---")
        if self.sheriff_id and self.sheriff_id in alive:
            logger.info(f"（警长：玩家{self.sheriff_id}号，最后发言）")

        recent_speeches = self._all_recent_speeches()
        recent_votes = self._all_recent_votes()

        for pid in current_order:
            player = self.players[pid - 1]
            if not player.is_alive:
                continue

            private = self._private_info(player)
            speech = await player.generate_speech(
                self.day, alive, self._tonight_deaths,
                recent_speeches, recent_votes, private,
            )
            self._speech_generation += 1
            tag = " [警长]" if pid == self.sheriff_id else ""
            logger.info(self._public(f"🎤 玩家{pid}号({ROLE_DISPLAY[player.role]}){tag}：{speech}\n"))
            self._add_event("speech", f"🎤 玩家{pid}号{tag}：{speech}", pid)
            self._emit_state()

            # Update shared context for next speakers
            recent_speeches = self._all_recent_speeches()

        self.phase = GamePhase.VOTING
        self._emit_state()

    async def do_voting_phase(self) -> None:
        """All alive players vote to eliminate someone."""
        alive = self.alive_ids()
        if len(alive) <= 1:
            self._check_win()
            return

        logger.info(f"\n--- 投票环节（第{self.day}天）---")

        # Collect all today's speeches for context
        today_speeches = self._today_speeches_text()
        death_summary = self._death_summary()
        recent_votes = self._all_recent_votes()

        votes: dict[int, int] = {}  # voter_id -> target_id
        tasks = []
        voters: list[int] = []

        for pid in alive:
            player = self.players[pid - 1]
            private = self._private_info(player)
            voters.append(pid)
            tasks.append(
                player.vote_decision(
                    self.day, alive, today_speeches,
                    death_summary, recent_votes, private,
                )
            )

        results = await asyncio.gather(*tasks)

        for voter_id, target in zip(voters, results):
            if target is not None:
                votes[voter_id] = target
                logger.info(f"🗳️ 玩家{voter_id}号 → 投票放逐 玩家{target}号")
                self._add_event("vote", f"🗳️ 玩家{voter_id}号 → 放逐 玩家{target}号")
            else:
                logger.info(f"🚫 玩家{voter_id}号 选择弃票")
                self._add_event("vote", f"🚫 玩家{voter_id}号 选择弃票")

        self._vote_generation += 1
        self._emit_state()

        # Tally votes — sheriff gets 1.5 votes
        tally: dict[int, float] = {}
        for voter_id, target in votes.items():
            weight = 1.5 if voter_id == self.sheriff_id else 1.0
            tally[target] = tally.get(target, 0.0) + weight
            if weight == 1.5:
                logger.debug(f"警长{voter_id}号投票权重 1.5")

        if not tally:
            logger.info("无人被投票放逐（平票或无效投票）")
            self._add_event("vote", "⚖️ 无人被投票放逐")
            self._emit_state()
            await self._after_vote()
            return

        # Show full vote distribution
        logger.info("\n📊 投票票型：")
        sorted_tally = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        tally_event_parts = []
        for pid, count in sorted_tally:
            voters_for = [v for v, t in votes.items() if t == pid]
            tag = " (警长1.5票)" if self.sheriff_id in voters_for else ""
            supporters = [f"{v}号" for v in voters_for]
            logger.info(self._public(f"  玩家{pid}号({ROLE_DISPLAY[self._role_of(pid)]})：{count}票{tag}  ← {', '.join(supporters)}"))
            tally_event_parts.append(f"玩家{pid}号 {count}票{tag} ← {', '.join(supporters)}")
        self._add_event("vote", f"📊 投票票型：{'；'.join(tally_event_parts)}")
        logger.info("")

        if len(sorted_tally) > 1 and sorted_tally[0][1] == sorted_tally[1][1]:
            logger.info(f"⚖️ 平票！最高票数 {sorted_tally[0][1]} 票，无人被放逐")
            self._add_event("vote", f"⚖️ 平票！无人被放逐")
            self._emit_state()
            await self._after_vote()
            return

        eliminated = sorted_tally[0][0]
        eliminated_role = ROLE_DISPLAY[self._role_of(eliminated)]
        logger.info(self._public(f"\n🚫 玩家{eliminated}号({eliminated_role}) 被投票放逐！"))
        self.players[eliminated - 1].kill()
        self._death_log.append(f"第{self.day}天：玩家{eliminated}号被投票放逐")
        self._add_event("eliminate", f"🚫 玩家{eliminated}号 被投票放逐！", eliminated)

        # Record death in all memories
        for p in self.players:
            p.memory.add_death(eliminated, self.day)

        # Hunter revenge shot
        if self._role_of(eliminated) == Role.HUNTER:
            shot_target = await self._hunter_shot(eliminated, "投票放逐")
            if shot_target is not None:
                await self._handle_sheriff_death(shot_target)

        # Sheriff death: pass the badge
        await self._handle_sheriff_death(eliminated)

        self._emit_state()
        await self._after_vote()

    async def _after_vote(self) -> None:
        """Check win conditions, then go to night."""
        if self._check_win():
            return
        self.phase = GamePhase.NIGHT

    # ------------------------------------------------------------------
    # Win detection
    # ------------------------------------------------------------------

    def _check_win(self) -> bool:
        """Check if either team has won. Returns True if game is over."""
        alive = self.alive_ids()
        alive_werewolves = [i for i in alive if self._role_of(i) == Role.WEREWOLF]
        alive_good = [i for i in alive if self._role_of(i) != Role.WEREWOLF]

        # All werewolves dead → good wins
        if not alive_werewolves:
            self._declare_win(Team.GOOD)
            return True

        # Werewolves outnumber or equal good players → evil wins
        if len(alive_werewolves) >= len(alive_good):
            self._declare_win(Team.EVIL)
            return True

        # All villagers dead or all special roles dead → evil wins (屠边)
        alive_villagers = [i for i in alive if self._role_of(i) == Role.VILLAGER]
        alive_special = [i for i in alive if self._role_of(i) in (Role.SEER, Role.WITCH, Role.HUNTER)]
        if not alive_villagers or not alive_special:
            self._declare_win(Team.EVIL)
            return True

        return False

    def _declare_win(self, team: Team) -> None:
        self.phase = GamePhase.GAME_OVER
        if team == Team.GOOD:
            logger.info("\n🎉 好人阵营胜利！所有狼人已被消灭！")
            self._add_event("game_over", "🎉 好人阵营胜利！所有狼人已被消灭！")
        else:
            logger.info("\n🐺 狼人阵营胜利！屠边成功！")
            self._add_event("game_over", "🐺 狼人阵营胜利！屠边成功！")
        self._emit_state()

    # ------------------------------------------------------------------
    # Referee modes
    # ------------------------------------------------------------------

    async def run_ai_referee(self) -> None:
        """AI referee mode — auto-advances through all phases."""
        logger.info("🤖 AI裁判模式：游戏将自动推进")
        self.setup()
        self.show_status()

        delay = self.config.game_speed_delay

        while self.phase != GamePhase.GAME_OVER:
            # Night
            await self.do_night_phase()
            if self.phase == GamePhase.GAME_OVER:
                break
            await asyncio.sleep(delay)

            # Day announce
            self.do_day_announcement()
            if self.phase == GamePhase.GAME_OVER:
                break
            await asyncio.sleep(delay / 2)

            # Sheriff election (day 1 only)
            if self.phase == GamePhase.SHERIFF_ELECTION:
                await self.do_sheriff_election()
                if self.phase == GamePhase.GAME_OVER:
                    break
                await asyncio.sleep(delay)

            # Speaking
            await self.do_speaking_phase()
            if self.phase == GamePhase.GAME_OVER:
                break
            await asyncio.sleep(delay)

            # Voting
            await self.do_voting_phase()
            if self.phase == GamePhase.GAME_OVER:
                break
            await asyncio.sleep(delay)

        self._show_result()

    async def run_human_player_mode(self) -> None:
        """Human player mode — you play as one of 9 players against 8 AI."""
        if not self.players:
            self.setup_human_mode()

        human = self.players[self._human_player_id - 1]
        role_name = ROLE_DISPLAY[human.role]
        team = "狼人阵营" if get_team(human.role) == Team.EVIL else "好人阵营"
        ability = ROLE_ABILITY[human.role]

        logger.info("\n" + "=" * 50)
        logger.info("🐺 狼人杀 — 人类玩家模式")
        logger.info("=" * 50)
        logger.info(f"你的编号：玩家{self._human_player_id}号")
        logger.info(f"你的身份：{role_name}")
        logger.info(f"你的阵营：{team}")
        logger.info(f"你的能力：{ability}")
        if human.role == Role.WEREWOLF:
            allies = human.memory.werewolf_allies
            if allies:
                logger.info(f"你的狼队友：{'、'.join(f'{a}号' for a in allies)}")
        logger.info("=" * 50)

        human_alive = True
        while self.phase != GamePhase.GAME_OVER:
            # Night
            await self.do_night_phase()
            if self.phase == GamePhase.GAME_OVER:
                break

            if human_alive and not human.is_alive:
                human_alive = False
                logger.info("\n💀 你已死亡！游戏将自动进行，你可以继续观看战局。\n")

            # Day announce
            self.do_day_announcement()
            if self.phase == GamePhase.GAME_OVER:
                break

            # Sheriff election (day 1 only)
            if self.phase == GamePhase.SHERIFF_ELECTION:
                await self.do_sheriff_election()
                if self.phase == GamePhase.GAME_OVER:
                    break

            # Speaking
            await self.do_speaking_phase()
            if self.phase == GamePhase.GAME_OVER:
                break

            # Voting
            await self.do_voting_phase()
            if self.phase == GamePhase.GAME_OVER:
                break

            if human_alive and not human.is_alive:
                human_alive = False
                logger.info("\n💀 你已死亡！游戏将自动进行，你可以继续观看战局。\n")

        self._show_result()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def alive_ids(self) -> list[int]:
        return [p.player_id for p in self.players if p.is_alive]

    def _role_of(self, player_id: int) -> Role:
        return self.players[player_id - 1].role

    def _find_alive(self, role: Role):
        for p in self.players:
            if p.role == role and p.is_alive:
                return p
        return None

    def _public(self, msg: str) -> str:
        """Strip role annotations from public messages in human player mode."""
        if not self._human_player_mode:
            return msg
        return _ROLE_TAG_PATTERN.sub("", msg)

    def _death_summary(self) -> str:
        """Build a summary of all dead players for AI context with cause of death."""
        if not self._death_log:
            # Fallback for games started before _death_log was added
            dead = [p.player_id for p in self.players if not p.is_alive]
            if not dead:
                return "目前无人死亡。"
            return f"已死亡玩家：{'、'.join(f'{pid}号' for pid in dead)}"
        return "死亡记录：\n" + "\n".join(f"  - {entry}" for entry in self._death_log)

    def _private_info(self, player) -> str:
        """Build private info string for a player."""
        parts: list[str] = []
        if player.role == Role.WEREWOLF:
            allies = player.memory.get_alive_werewolf_allies(self.alive_ids())
            if allies:
                parts.append(f"（私密信息）你的狼队友是：{'、'.join(f'{a}号' for a in allies)}")
            if self._wolf_kill_log:
                parts.append("（私密信息）你们的击杀记录：")
                for entry in self._wolf_kill_log:
                    parts.append(f"  {entry}")
        elif player.role == Role.SEER:
            if player.memory.check_results:
                parts.append(f"（私密信息）你的查验记录：\n" + "\n".join(player.memory.check_results))
        elif player.role == Role.WITCH:
            parts.append(f"（私密信息）解药：{'未用' if not player.memory.antidote_used else '已用'}")
            parts.append(f"（私密信息）毒药：{'未用' if not player.memory.poison_used else '已用'}")
            if player.memory.antidote_used and self._witch_saved_target is not None:
                parts.append(f"（私密信息）第{self._witch_save_night}夜你使用解药救了 玩家{self._witch_saved_target}号")
            if player.memory.poison_used and self._witch_poisoned is not None:
                parts.append(f"（私密信息）第{self._witch_poison_night}夜你使用毒药毒了 玩家{self._witch_poisoned}号")
        elif player.role == Role.HUNTER:
            parts.append("（私密信息）你是猎人。被投票放逐或狼人击杀时可以开枪带走一人。")
        if self._sheriff_election_summary:
            parts.append(f"（公开信息）{self._sheriff_election_summary}")
        if self._sheriff_log:
            parts.append("（公开信息）警长记录：")
            for entry in self._sheriff_log:
                parts.append(f"  - {entry}")
        if self.sheriff_id is not None:
            parts.append(f"（公开信息）当前警长：玩家{self.sheriff_id}号（1.5票，最后发言）")
        parts.append(f"（公开信息）{self._death_summary()}")
        return "\n".join(parts)

    async def _hunter_shot(self, hunter_pid: int, death_cause: str) -> int | None:
        """Handle hunter's revenge shot when killed.

        Returns the shot target ID, or None if no valid target was chosen.
        The caller is responsible for handling sheriff death of the shot target.
        """
        logger.debug(f"\n🔫 猎人{hunter_pid}号因{death_cause}死亡，发动技能——开枪带走一人！")
        self._add_event("hunter_action", f"🔫 猎人{death_cause}死亡，可以发动技能开枪带走一人", hunter_pid)
        alive = self.alive_ids()
        recent_s = self._all_recent_speeches()
        recent_v = self._all_recent_votes()
        shot_target = await self.players[hunter_pid - 1].hunter_shot_decision(
            alive, death_cause, recent_s, recent_v, self._death_summary(),
        )
        if shot_target is not None and self.players[shot_target - 1].is_alive:
            shot_role = ROLE_DISPLAY[self._role_of(shot_target)]
            logger.debug(f"💥 猎人{hunter_pid}号开枪带走了 玩家{shot_target}号({shot_role})！")
            self._add_event("hunter_action", f"💥 猎人开枪带走了 玩家{shot_target}号！", shot_target)
            self.players[shot_target - 1].kill()
            death_day = self.night if "狼人" in death_cause else self.day
            if "狼人" in death_cause:
                self._tonight_deaths.append(shot_target)
            if "狼人" in death_cause:
                self._death_log.append(f"第{death_day}夜：玩家{shot_target}号死亡")
            else:
                self._death_log.append(f"第{death_day}天：玩家{shot_target}号被猎人开枪带走")
            for p in self.players:
                p.memory.add_death(shot_target, death_day)
        return shot_target

    async def _handle_sheriff_death(self, dead_pid: int) -> None:
        """If the dead player was sheriff, let them choose to destroy or pass the badge."""
        if dead_pid != self.sheriff_id:
            return
        alive = self.alive_ids()
        if not alive:
            self.sheriff_id = None
            return
        sheriff_player = self.players[dead_pid - 1]
        recent_s = self._all_recent_speeches()
        recent_v = self._all_recent_votes()
        private = self._private_info(sheriff_player)

        # Ask dying sheriff whether to destroy the badge (撕警徽)
        destroy = await sheriff_player.sheriff_destroy_badge_decision(
            alive, recent_s, recent_v, private,
        )
        if destroy:
            self.sheriff_id = None
            logger.info(self._public(f"📛 警长{dead_pid}号死亡，选择撕毁警徽！本局不再有警长。"))
            self._sheriff_log.append(f"警长{dead_pid}号死亡，撕毁警徽")
            self._add_event("election", f"📛 警长{dead_pid}号死亡，撕毁警徽！警徽被销毁。")
            self._emit_state()
            return

        successor = await sheriff_player.sheriff_successor_decision(alive, recent_s, recent_v, private)
        if successor is not None and successor in alive:
            self.sheriff_id = successor
            logger.info(self._public(f"📛 警长{dead_pid}号死亡，将警徽移交给 玩家{successor}号({ROLE_DISPLAY[self._role_of(successor)]})"))
            self._sheriff_log.append(f"警长{dead_pid}号死亡，移交警徽给 玩家{successor}号")
        elif alive:
            self.sheriff_id = random.choice(alive)
            logger.info(f"📛 警长{dead_pid}号死亡，随机指定 玩家{self.sheriff_id}号 为新警长")
            self._sheriff_log.append(f"警长{dead_pid}号死亡，随机指定 玩家{self.sheriff_id}号 为新警长")
        else:
            self.sheriff_id = None

    def _build_speech_order(self, alive: list[int]) -> list[int]:
        """Build speaking order: alternates direction each day, sheriff always last."""
        order = sorted(alive)
        if self.sheriff_id and self.sheriff_id in order:
            order.remove(self.sheriff_id)
            # Snake order: odd days ascending, even days descending
            if self.day % 2 == 0:
                order.reverse()
            order.append(self.sheriff_id)
        else:
            if self.day % 2 == 0:
                order.reverse()
        return order

    def _all_recent_speeches(self) -> str:
        if self._speech_generation == self._speech_cache_version:
            return self._speech_cache
        all_speeches: list[str] = []
        for p in self.players:
            for s in p.memory.speeches:
                all_speeches.append(f"Day{s.day} 玩家{s.player_id}号：{s.content}")
        if not all_speeches:
            result = "（暂无发言记录）"
        else:
            result = "\n".join(all_speeches[-20:])
        self._speech_cache = result
        self._speech_cache_version = self._speech_generation
        return result

    def _all_recent_votes(self) -> str:
        if self._vote_generation == self._vote_cache_version:
            return self._vote_cache
        all_votes: list[str] = []
        # Sheriff election votes first (only on Day 1)
        for p in self.players:
            for v in p.memory.sheriff_votes:
                all_votes.append(f"警长竞选 玩家{v.voter_id}号→玩家{v.target_id}号")
        # Regular elimination votes
        for p in self.players:
            for v in p.memory.votes:
                all_votes.append(f"Day{v.day} 玩家{v.voter_id}号→玩家{v.target_id}号")
        if not all_votes:
            result = "（暂无投票记录）"
        else:
            result = "\n".join(all_votes[-20:])
        self._vote_cache = result
        self._vote_cache_version = self._vote_generation
        return result

    def _today_speeches_text(self) -> str:
        lines: list[str] = []
        for p in self.players:
            for s in p.memory.speeches:
                if s.day == self.day:
                    lines.append(f"玩家{s.player_id}号：{s.content}")
        return "\n".join(lines) if lines else "（今日无发言）"

    def show_status(self, show_roles: bool = True) -> None:
        """Print current game status (referee's all-knowing view).

        When show_roles is False, role and team columns are hidden.
        """
        logger.info(f"\n{'='*50}")
        logger.info(f"📋 游戏状态  |  第{self.night}夜 / 第{self.day}天  |  阶段：{self.phase.value}")
        if self.sheriff_id:
            if show_roles:
                logger.info(f"🎖️ 警长：玩家{self.sheriff_id}号({ROLE_DISPLAY[self._role_of(self.sheriff_id)]})")
            else:
                logger.info(f"🎖️ 警长：玩家{self.sheriff_id}号")
        logger.info(f"{'='*50}")
        if show_roles:
            logger.info(f"{'编号':<6} {'身份':<10} {'状态':<8} {'阵营':<10}")
            logger.info("-" * 36)
            for p in self.players:
                status = "存活" if p.is_alive else "💀死亡"
                team = "狼人" if get_team(p.role) == Team.EVIL else "好人"
                badge = " ★警长" if p.player_id == self.sheriff_id else ""
                logger.info(f"玩家{p.player_id}号  {ROLE_DISPLAY[p.role]:<8} {status:<8} {team}{badge}")
        else:
            logger.info(f"{'编号':<6} {'状态':<8}")
            logger.info("-" * 16)
            for p in self.players:
                status = "存活" if p.is_alive else "💀死亡"
                badge = " ★警长" if p.player_id == self.sheriff_id else ""
                logger.info(f"玩家{p.player_id}号  {status:<8}{badge}")
        logger.info(f"{'='*50}")

    def _show_result(self) -> None:
        """Show final game result."""
        logger.info("\n=== 游戏结束 ===")
        for p in self.players:
            status = "存活" if p.is_alive else "死亡"
            logger.info(f"玩家{p.player_id}号：{ROLE_DISPLAY[p.role]}（{status}）")

    # ------------------------------------------------------------------
    # State callback (for web UI)
    # ------------------------------------------------------------------

    def set_state_callback(self, cb: Callable[[dict], None]) -> None:
        self._state_callback = cb

    def _add_event(self, event_type: str, text: str, player_id: int | None = None) -> None:
        self._event_log.append({"type": event_type, "text": text, "player_id": player_id})

    def _emit_state(self) -> None:
        if self._state_callback is None:
            return
        self._state_generation += 1
        alive = self.alive_ids()
        # Determine werewolf allies for the human player (if applicable)
        human_ally_ids: set[int] = set()
        if self._human_player_mode and self._human_player_id:
            human_player = self.players[self._human_player_id - 1]
            if human_player.role == Role.WEREWOLF:
                human_ally_ids = set(human_player.memory.werewolf_allies)
        players_state = []
        for p in self.players:
            is_human = p.player_id == self._human_player_id
            is_ally = p.player_id in human_ally_ids
            if self._human_player_mode:
                game_over = self.phase == GamePhase.GAME_OVER
                players_state.append({
                    "id": p.player_id,
                    "name": f"玩家{p.player_id}号",
                    "role": ROLE_DISPLAY[p.role] if (is_human or is_ally or game_over) else "???",
                    "is_alive": p.is_alive,
                    "is_sheriff": p.player_id == self.sheriff_id,
                    "is_human": is_human,
                    "is_ally": is_ally,
                    "team": ("evil" if get_team(p.role) == Team.EVIL else "good") if (is_human or is_ally or game_over) else "unknown",
                })
            else:
                players_state.append({
                    "id": p.player_id,
                    "name": f"玩家{p.player_id}号",
                    "role": ROLE_DISPLAY[p.role],
                    "is_alive": p.is_alive,
                    "is_sheriff": p.player_id == self.sheriff_id,
                    "is_human": is_human,
                    "is_ally": False,
                    "team": "evil" if get_team(p.role) == Team.EVIL else "good",
                })

        events = list(self._event_log)
        if self._human_player_mode:
            human_player = self.players[self._human_player_id - 1]
            human_role = human_player.role
            filtered_types = set(_PRIVATE_EVENT_TYPES)
            # Let the human player see events relevant to their own role
            if human_role == Role.WEREWOLF:
                filtered_types.discard("wolf_discuss")
                filtered_types.discard("wolf_action")
            if human_role == Role.SEER:
                filtered_types.discard("seer_check")
            if human_role == Role.WITCH:
                filtered_types.discard("witch_action")
            events = [e for e in events if e["type"] not in filtered_types]

        state = {
            "generation": self._state_generation,
            "phase": self.phase.value,
            "night": self.night,
            "day": self.day,
            "sheriff_id": self.sheriff_id,
            "tonight_deaths": list(self._tonight_deaths),
            "death_log": list(self._death_log),
            "sheriff_election_summary": self._sheriff_election_summary,
            "sheriff_log": list(self._sheriff_log),
            "game_over": self.phase == GamePhase.GAME_OVER,
            "winner": None,
            "players": players_state,
            "events": events,
            "human_player_id": self._human_player_id,
            "human_player_alive": self._human_player_id is not None and self.players[self._human_player_id - 1].is_alive if self._human_player_id else None,
        }
        self._state_callback(state)