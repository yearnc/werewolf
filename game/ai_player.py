"""AI player driven by LLM calls for decision-making."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

from config import Config
from memory import PlayerMemory, Speech, VoteRecord
from player import Player
from role import ROLE_DISPLAY, ROLE_ABILITY, Role, get_team_display
from utils import extract_player_number, logger, parse_witch_decision

if TYPE_CHECKING:
    from llm_client import LLMClient


class AIPlayer(Player):
    """An AI-controlled werewolf player that uses LLM for all decisions."""

    def __init__(self, player_id: int, role: Role, config: Config, llm_client: LLMClient):
        super().__init__(player_id)
        self.role = role
        self.config = config
        self.llm = llm_client
        self.memory = PlayerMemory(
            player_id=player_id,
            role=ROLE_DISPLAY[role],
        )

    # ------------------------------------------------------------------
    # Night actions
    # ------------------------------------------------------------------

    async def wolf_discussion_speak(
        self,
        night: int,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        discussion_history: str,
        round_num: int,
        total_rounds: int,
        death_summary: str,
        wolf_kill_history: str = "",
        past_discussions: str = "",
    ) -> str:
        """Speak during the wolf discussion round."""
        from prompts import build_wolf_discussion_prompt

        allies = self.memory.get_alive_werewolf_allies(alive_ids)
        non_allies = [i for i in alive_ids if i not in allies and i != self.player_id]
        dead_ids = [i for i in range(1, 10) if i not in alive_ids]

        prompt = build_wolf_discussion_prompt(
            self.player_id, night, allies, non_allies,
            recent_speeches, recent_votes, discussion_history,
            round_num, total_rounds, death_summary,
            suspicions=self.memory.suspicion_summary(),
            wolf_kill_history=wolf_kill_history,
            past_discussions=past_discussions,
            dead_ids=dead_ids,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        if not response or not response.strip():
            response = "我同意队友的意见，今晚就刀那个最像神的。"
        return response.strip()

    async def werewolf_kill_decision(
        self,
        night: int,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        discussion_summary: str,
        death_summary: str,
        wolf_kill_history: str = "",
    ) -> Optional[int]:
        """Ask the LLM to pick a kill target. Returns player ID or None."""
        from prompts import build_werewolf_night_prompt

        allies = self.memory.get_alive_werewolf_allies(alive_ids)
        # All alive players are valid targets; prompt guides against killing allies
        valid_targets = list(alive_ids)
        dead_ids = [i for i in range(1, 10) if i not in alive_ids]

        prompt = build_werewolf_night_prompt(
            self.player_id, night, valid_targets, allies,
            recent_speeches, recent_votes, discussion_summary, death_summary,
            suspicions=self.memory.suspicion_summary(),
            wolf_kill_history=wolf_kill_history,
            dead_ids=dead_ids,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        target = extract_player_number(response or "", valid_targets)

        if target is None:
            target = random.choice(valid_targets)
            logger.debug(f"狼人{self.player_id}号 LLM 返回无效，随机选择目标 {target}号")

        logger.debug(f"狼人{self.player_id}号 选择击杀 玩家{target}号")
        return target

    async def seer_check_decision(
        self,
        night: int,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        death_summary: str = "",
    ) -> Optional[int]:
        """Ask the LLM to pick a player to check. Returns player ID or None."""
        from prompts import build_seer_night_prompt

        # Don't check self; don't re-check already checked players
        already_checked = set()
        for entry in self.memory.check_results:
            import re
            nums = re.findall(r"\d+", entry)
            if nums:
                already_checked.add(int(nums[1]))  # target is the second number

        valid_targets = [i for i in alive_ids if i != self.player_id and i not in already_checked]
        if not valid_targets:
            valid_targets = [i for i in alive_ids if i != self.player_id]

        check_history = "\n".join(self.memory.check_results) if self.memory.check_results else "（尚无查验记录）"

        dead_ids = [i for i in range(1, 10) if i not in alive_ids]

        prompt = build_seer_night_prompt(
            self.player_id, night, valid_targets,
            check_history, recent_speeches, recent_votes,
            death_summary=death_summary,
            suspicions=self.memory.suspicion_summary(),
            dead_ids=dead_ids,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        target = extract_player_number(response or "", valid_targets)

        if target is None:
            target = random.choice(valid_targets)
            logger.debug(f"预言家{self.player_id}号 LLM 返回无效，随机选择查验 {target}号")

        logger.debug(f"预言家{self.player_id}号 选择查验 玩家{target}号")
        return target

    async def witch_night_decision(
        self,
        night: int,
        alive_ids: list[int],
        attacked_id: int | None,
        recent_speeches: str,
        recent_votes: str,
        death_summary: str = "",
    ) -> tuple[str, Optional[int]]:
        """Ask the LLM for witch potion decision.

        Returns (action, target_id) where action is "save"/"poison"/"none".
        """
        from prompts import build_witch_night_prompt

        prompt = build_witch_night_prompt(
            self.player_id, night, alive_ids, attacked_id,
            not self.memory.antidote_used,
            not self.memory.poison_used,
            recent_speeches, recent_votes,
            death_summary=death_summary,
            suspicions=self.memory.suspicion_summary(),
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)

        action, target = parse_witch_decision(response or "", alive_ids)

        # Validate
        if action == "save" and self.memory.antidote_used:
            action = "none"
        if action == "poison" and self.memory.poison_used:
            action = "none"
        # Witch cannot poison herself
        if action == "poison" and target == self.player_id:
            candidates = [i for i in alive_ids if i != self.player_id]
            target = random.choice(candidates) if candidates else None
            logger.debug(f"女巫{self.player_id}号不能毒自己，随机选择 {target}号")
        # Don't poison the player already killed by wolves (waste of poison)
        if action == "poison" and target is not None and target == attacked_id:
            logger.debug(f"女巫{self.player_id}号试图毒杀已死亡的狼刀目标 {attacked_id}号，视为无效操作")
            action = "none"
            target = None
        if action == "poison" and target is None:
            # Pick random alive non-self
            candidates = [i for i in alive_ids if i != self.player_id]
            target = random.choice(candidates) if candidates else None
            logger.debug(f"女巫毒药目标无效，随机选择 {target}号")

        logger.debug(f"女巫{self.player_id}号 决定：{action} {target or ''}")
        return action, target

    async def hunter_shot_decision(
        self,
        alive_ids: list[int],
        death_cause: str,
        recent_speeches: str,
        recent_votes: str,
        death_summary: str = "",
    ) -> int | None:
        """Hunter's revenge shot when killed. Returns target player ID."""
        from prompts import build_hunter_shot_prompt

        valid_targets = [i for i in alive_ids if i != self.player_id]
        if not valid_targets:
            return None

        suspicions = self.memory.suspicion_summary()

        dead_ids = [i for i in range(1, 10) if i not in alive_ids]

        prompt = build_hunter_shot_prompt(
            self.player_id, valid_targets, death_cause,
            recent_speeches, recent_votes, suspicions,
            death_summary=death_summary,
            dead_ids=dead_ids,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        target = extract_player_number(response or "", valid_targets)

        if target is None:
            target = random.choice(valid_targets)
            logger.debug(f"猎人{self.player_id}号 LLM 射击无效，随机选择 {target}号")

        logger.debug(f"猎人{self.player_id}号 开枪带走 玩家{target}号")
        return target

    async def sheriff_candidacy_decision(
        self,
        alive_ids: list[int],
        death_summary: str,
        private_info: str,
        current_candidates: list[int] | None = None,
    ) -> bool:
        """Decide whether to run for sheriff. Returns True to run, False to pass."""
        from prompts import build_sheriff_candidacy_prompt

        prompt = build_sheriff_candidacy_prompt(
            self.player_id, self.role, alive_ids, death_summary, private_info, current_candidates,
        )
        system = _build_system(self.player_id, self.role)

        import re
        response = await self.llm.chat(system, prompt)
        text = (response or "").strip().lower()
        if re.search(r"\bpass\b", text):
            return False
        if re.search(r"\brun\b", text):
            return True
        # Default: run if special role, pass if villager
        return self.role not in (Role.VILLAGER,)

    async def generate_campaign_speech(
        self,
        alive_ids: list[int],
        death_summary: str,
        private_info: str,
    ) -> str:
        """Generate a sheriff campaign speech."""
        from prompts import build_sheriff_campaign_prompt

        prompt = build_sheriff_campaign_prompt(
            self.player_id, self.role, alive_ids, death_summary, private_info,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        if not response or not response.strip():
            response = "我想当警长，带领好人走向胜利。"
        speech = response.strip()
        # Record campaign speech in memory so other players see it during speaking phase
        self.memory.add_speech(Speech(self.player_id, f"(竞选警长) {speech}", 1))
        return speech

    async def sheriff_withdraw_decision(
        self,
        candidates: list[int],
        campaign_speeches: dict[int, str],
        private_info: str,
        death_summary: str = "",
    ) -> bool:
        """Decide whether to withdraw from sheriff election. Returns True to withdraw."""
        from prompts import build_sheriff_withdraw_prompt

        prompt = build_sheriff_withdraw_prompt(
            self.player_id, self.role, candidates,
            campaign_speeches, private_info, death_summary,
        )
        system = _build_system(self.player_id, self.role)

        import re
        response = await self.llm.chat(system, prompt)
        text = (response or "").strip().lower()
        if re.search(r"\bstay\b", text):
            return False
        if re.search(r"\bwithdraw\b", text):
            return True
        # Default: stay in the race
        return False

    async def sheriff_vote_decision(
        self,
        candidates: list[int],
        campaign_speeches: str,
        private_info: str,
        death_summary: str = "",
    ) -> int | None:
        """Vote for a sheriff candidate."""
        from prompts import build_sheriff_vote_prompt

        valid_targets = [i for i in candidates if i != self.player_id]
        suspicions = self.memory.suspicion_summary()
        prompt = build_sheriff_vote_prompt(
            self.player_id, self.role, valid_targets,
            campaign_speeches, private_info, suspicions,
            death_summary=death_summary,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        target = extract_player_number(response or "", valid_targets)
        if target is None and valid_targets:
            target = random.choice(valid_targets)
        return target

    async def sheriff_destroy_badge_decision(
        self,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        private_info: str,
    ) -> bool:
        """Dying sheriff decides whether to destroy the badge. Returns True to destroy."""
        from prompts import build_sheriff_destroy_badge_prompt

        prompt = build_sheriff_destroy_badge_prompt(
            self.player_id, self.role, alive_ids,
            recent_speeches, recent_votes, private_info,
        )
        system = _build_system(self.player_id, self.role)

        import re
        response = await self.llm.chat(system, prompt)
        text = (response or "").strip().lower()
        if re.search(r"\bpass\b", text):
            return False
        if re.search(r"\bdestroy\b", text):
            return True
        # Default: pass the badge
        return False

    async def sheriff_successor_decision(
        self,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        private_info: str,
    ) -> int | None:
        """Dying sheriff picks a successor."""
        from prompts import build_sheriff_successor_prompt

        valid_targets = [i for i in alive_ids if i != self.player_id]
        if not valid_targets:
            return None

        suspicions = self.memory.suspicion_summary()

        prompt = build_sheriff_successor_prompt(
            self.player_id, valid_targets, recent_speeches, recent_votes,
            suspicions, private_info,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        target = extract_player_number(response or "", valid_targets)
        if target is None and valid_targets:
            target = random.choice(valid_targets)
        return target

    # ------------------------------------------------------------------
    # Day actions
    # ------------------------------------------------------------------

    async def generate_speech(
        self,
        day: int,
        alive_ids: list[int],
        deaths_today: list[int],
        recent_speeches: str,
        recent_votes: str,
        private_info: str,
    ) -> str:
        """Generate a speech for the current day."""
        from prompts import build_speak_prompt

        if deaths_today:
            death_text = f"昨晚死亡的玩家：{'、'.join(f'{d}号' for d in deaths_today)}"
        elif day == 1:
            death_text = "昨晚是平安夜，无人死亡。"
        else:
            death_text = "昨晚是平安夜，无人死亡。"

        suspicions = self.memory.suspicion_summary()

        prompt = build_speak_prompt(
            self.player_id, self.role, day, alive_ids,
            death_text, recent_speeches, recent_votes, private_info, suspicions,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)

        if not response or not response.strip():
            fallback_speeches = [
                "我过。",
                "我是个普通村民，没什么信息，先听听大家的发言。",
                "目前信息还不够，暂不发表意见。",
                "我先观察一下局势，听听后面的人怎么说。",
            ]
            response = random.choice(fallback_speeches)
            logger.debug(f"玩家{self.player_id}号 LLM 发言为空，使用默认发言")

        speech = response.strip()
        # Record in memory
        self.memory.add_speech(Speech(self.player_id, speech, day))
        return speech

    async def vote_decision(
        self,
        day: int,
        alive_ids: list[int],
        today_speeches: str,
        death_summary: str,
        recent_votes: str,
        private_info: str,
    ) -> Optional[int]:
        """Ask the LLM to vote for elimination. Returns target player ID, or None to abstain."""
        from prompts import build_vote_prompt

        valid_targets = [i for i in alive_ids if i != self.player_id]
        suspicions = self.memory.suspicion_summary()

        prompt = build_vote_prompt(
            self.player_id, self.role, day,
            valid_targets, today_speeches, death_summary, recent_votes,
            private_info, suspicions,
        )
        system = _build_system(self.player_id, self.role)

        response = await self.llm.chat(system, prompt)
        text = response or ""

        # Check for abstention — explicit zero or Chinese abstention keywords
        abstain_kw = ("弃票", "弃权", "abstain", "放弃", "不投票")
        if any(kw in text for kw in abstain_kw):
            logger.debug(f"玩家{self.player_id}号 选择弃票")
            return None
        import re
        nums = re.findall(r"\d+", text)
        if nums and int(nums[0]) == 0:
            logger.debug(f"玩家{self.player_id}号 选择弃票")
            return None

        target = extract_player_number(text, valid_targets)

        if target is None:
            target = random.choice(valid_targets)
            logger.debug(f"玩家{self.player_id}号 LLM 投票无效，随机投票 {target}号")

        self.memory.add_vote(VoteRecord(self.player_id, target, day))
        return target


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_system_cache: dict[tuple[int, str], str] = {}

def _build_system(player_id: int, role: Role) -> str:
    key = (player_id, role.value)
    if key not in _system_cache:
        from prompts import build_system_prompt
        _system_cache[key] = build_system_prompt(player_id, role)
    return _system_cache[key]
