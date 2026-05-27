"""Human player controlled via CLI input."""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

from config import Config
from memory import PlayerMemory, Speech, VoteRecord
from player import Player
from role import ROLE_ABILITY, ROLE_DISPLAY, Role

class HumanPlayer(Player):
    """A human player that makes decisions via CLI input."""

    def __init__(self, player_id: int, role: Role, config: Config):
        super().__init__(player_id)
        self.role = role
        self.config = config
        self.memory = PlayerMemory(
            player_id=player_id,
            role=ROLE_DISPLAY[role],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _input(prompt: str) -> str:
        """Get CLI input from the human player."""
        try:
            return await asyncio.to_thread(input, prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    async def _input_choice(
        self, prompt: str, valid_choices: list[int], allow_zero: bool = False,
    ) -> Optional[int]:
        """Get a validated numeric choice from the human. Returns None for 0."""
        while True:
            raw = await self._input(prompt)
            try:
                num = int(raw.strip())
                if num in valid_choices:
                    return num
                if allow_zero and num == 0:
                    return None
                print(f"  无效选择，请输入 {'/'.join(str(c) for c in valid_choices)}" + (" 或 0=弃权" if allow_zero else ""))
            except (ValueError, EOFError):
                print("  输入无效，请输入数字")

    async def _input_bool(self, prompt: str) -> bool:
        """Get a yes/no decision from the human."""
        while True:
            raw = await self._input(prompt)
            text = raw.strip().lower()
            if text in ("y", "yes", "是", "1", "run"):
                return True
            if text in ("n", "no", "否", "0", "pass"):
                return False
            print("  请输入 y(是) 或 n(否)")

    def _alive_str(self, alive_ids: list[int]) -> str:
        return ", ".join(f"玩家{i}号" for i in alive_ids)

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
        """Wolf discussion — show context and get speech."""
        allies = self.memory.get_alive_werewolf_allies(alive_ids)
        print(f"\n  ┌─ 🐺 狼人讨论 第{night}夜 第{round_num}/{total_rounds}轮 ─────────────┐")
        print(f"  │ 你的狼队友：{'、'.join(f'{a}号' for a in allies)}")
        print(f"  │ {death_summary}")
        if discussion_history:
            print(f"  │ 已有讨论：")
            for line in discussion_history.split("\n"):
                print(f"  │   {line}")
        print(f"  └{'─' * 46}┘")
        while True:
            speech = await self._input("  💬 你的讨论发言: ")
            if speech.strip():
                return speech.strip()
            print("  发言不能为空")

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
        """Wolf kill — choose target."""
        allies = self.memory.get_alive_werewolf_allies(alive_ids)
        valid = list(alive_ids)
        print(f"\n  ┌─ 🔪 狼人击杀决策 第{night}夜 ─────────────────────┐")
        print(f"  │ {death_summary}")
        print(f"  │ 讨论总结：{discussion_summary}")
        print(f"  │ 可击杀目标：{self._alive_str(valid)}")
        print(f"  └{'─' * 46}┘")
        return await self._input_choice("  请选择击杀目标编号: ", valid)

    async def seer_check_decision(
        self,
        night: int,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        death_summary: str = "",
    ) -> Optional[int]:
        """Seer check — choose player to investigate."""
        already_checked: set[int] = set()
        for entry in self.memory.check_results:
            import re
            nums = re.findall(r"\d+", entry)
            if nums:
                already_checked.add(int(nums[1]))
        valid = [i for i in alive_ids if i != self.player_id and i not in already_checked]
        if not valid:
            valid = [i for i in alive_ids if i != self.player_id]

        check_history = "\n".join(self.memory.check_results) if self.memory.check_results else "（尚无查验记录）"
        print(f"\n  ┌─ 🔮 预言家查验 第{night}夜 ────────────────────────┐")
        print(f"  │ 查验记录：{check_history}")
        print(f"  │ 可查验目标：{self._alive_str(valid)}")
        print(f"  └{'─' * 46}┘")
        return await self._input_choice("  请选择查验目标编号: ", valid)

    async def witch_night_decision(
        self,
        night: int,
        alive_ids: list[int],
        attacked_id: int | None,
        recent_speeches: str,
        recent_votes: str,
        death_summary: str = "",
    ) -> tuple[str, Optional[int]]:
        """Witch potion decision."""
        death_info = f"玩家{attacked_id}号" if attacked_id else "无人被杀"
        antidote = "可用" if not self.memory.antidote_used else "已用"
        poison = "可用" if not self.memory.poison_used else "已用"
        self_hint = ""
        if attacked_id is not None and attacked_id == self.player_id and not self.memory.antidote_used:
            self_hint = "\n  │ ⚠️ 今晚狼人的击杀目标就是你自己！你可以使用解药自救。"

        print(f"\n  ┌─ 🧪 女巫用药 第{night}夜 ────────────────────────────┐")
        print(f"  │ 狼人击杀目标：{death_info}{self_hint}")
        print(f"  │ 解药：{antidote} | 毒药：{poison}")
        print(f"  │ 存活玩家：{self._alive_str(alive_ids)}")
        print(f"  └{'─' * 46}┘")

        while True:
            raw = await self._input("  请选择行动 (save / poison N / none): ")
            text = raw.strip().lower()
            if text == "save" and not self.memory.antidote_used:
                return ("save", None)
            if text == "save" and self.memory.antidote_used:
                print("  解药已用，无法再次使用")
                continue
            if text.startswith("poison"):
                if self.memory.poison_used:
                    print("  毒药已用，无法再次使用")
                    continue
                parts = text.split()
                if len(parts) >= 2:
                    try:
                        target = int(parts[1])
                        if target == self.player_id:
                            print("  不能毒自己")
                            continue
                        if target == attacked_id:
                            print("  该玩家已被狼人击杀，毒他浪费")
                            continue
                        if target in alive_ids:
                            return ("poison", target)
                    except ValueError:
                        pass
                print(f"  请输入 poison N（N为玩家编号），例如 poison 3")
                continue
            if text == "none":
                return ("none", None)
            print("  无效输入，请输入 save / poison N / none")

    async def hunter_shot_decision(
        self,
        alive_ids: list[int],
        death_cause: str,
        recent_speeches: str,
        recent_votes: str,
        death_summary: str = "",
    ) -> int | None:
        """Hunter revenge shot."""
        valid = [i for i in alive_ids if i != self.player_id]
        if not valid:
            return None
        suspicions = self.memory.suspicion_summary()
        print(f"\n  ┌─ 🔫 猎人开枪 ───────────────────────────────────┐")
        print(f"  │ 死因：{death_cause}")
        print(f"  │ 怀疑对象：{suspicions}")
        print(f"  │ 可射击目标：{self._alive_str(valid)}")
        print(f"  └{'─' * 46}┘")
        return await self._input_choice("  请选择射击目标 (输入 0 放弃): ", valid, allow_zero=True)

    async def sheriff_candidacy_decision(
        self,
        alive_ids: list[int],
        death_summary: str,
        private_info: str,
        current_candidates: list[int] | None = None,
    ) -> bool:
        """Decide whether to run for sheriff."""
        print(f"\n  ┌─ 🎖️ 警长竞选报名 ────────────────────────────────┐")
        print(f"  │ 存活玩家：{self._alive_str(alive_ids)}")
        print(f"  │ {death_summary}")
        if current_candidates:
            print(f"  │ 已报名参选：{'、'.join(f'{c}号' for c in current_candidates)}")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        print(f"  └{'─' * 46}┘")
        return await self._input_bool("  是否参加警长竞选? (y/n): ")

    async def generate_campaign_speech(
        self,
        alive_ids: list[int],
        death_summary: str,
        private_info: str,
    ) -> str:
        """Generate a sheriff campaign speech."""
        print(f"\n  ┌─ 📢 竞选发言 ───────────────────────────────────┐")
        print(f"  │ {death_summary}")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        print(f"  └{'─' * 46}┘")
        while True:
            speech = await self._input("  💬 你的竞选发言: ")
            if speech.strip():
                self.memory.add_speech(Speech(self.player_id, f"(竞选警长) {speech.strip()}", 1))
                return speech.strip()
            print("  发言不能为空")

    async def sheriff_withdraw_decision(
        self,
        candidates: list[int],
        campaign_speeches: dict[int, str],
        private_info: str,
        death_summary: str = "",
    ) -> bool:
        """Decide whether to withdraw from sheriff election."""
        other = [c for c in candidates if c != self.player_id]
        print(f"\n  ┌─ 🏳️ 退水决定 ───────────────────────────────────┐")
        print(f"  │ 当前警上候选人：{'、'.join(f'{c}号' for c in candidates)}")
        print(f"  │ 其他候选人：{'、'.join(f'{c}号' for c in other) if other else '无'}")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        print(f"  └{'─' * 46}┘")
        return await self._input_bool("  是否退水? (y/n): ")

    async def sheriff_vote_decision(
        self,
        candidates: list[int],
        campaign_speeches: str,
        private_info: str,
        death_summary: str = "",
    ) -> int | None:
        """Vote for a sheriff candidate."""
        valid = [i for i in candidates if i != self.player_id]
        print(f"\n  ┌─ 🗳️ 警长投票 ───────────────────────────────────┐")
        print(f"  │ 请根据刚才的竞选发言选择警长。")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        print(f"  └{'─' * 46}┘")
        return await self._input_choice("  请选择你要投票的警长候选人编号: ", valid)

    async def sheriff_destroy_badge_decision(
        self,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        private_info: str,
    ) -> bool:
        """Dying sheriff decides whether to destroy the badge."""
        print(f"\n  ┌─ 📛 撕警徽 ───────────────────────────────────┐")
        print(f"  │ 你是警长，即将死亡。要撕毁警徽吗？")
        print(f"  │ 撕毁后本局不再有警长（无1.5票+无最后发言权）")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        print(f"  └{'─' * 46}┘")
        return await self._input_bool("  撕毁警徽? (y/n): ")

    async def sheriff_successor_decision(
        self,
        alive_ids: list[int],
        recent_speeches: str,
        recent_votes: str,
        private_info: str,
    ) -> int | None:
        """Dying sheriff picks a successor."""
        valid = [i for i in alive_ids if i != self.player_id]
        if not valid:
            return None
        print(f"\n  ┌─ 📛 警徽移交 ───────────────────────────────────┐")
        print(f"  │ 你是警长，即将死亡，请选择警徽继任者")
        print(f"  │ 存活玩家：{self._alive_str(valid)}")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        print(f"  └{'─' * 46}┘")
        return await self._input_choice("  请选择警徽继任者编号: ", valid)

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
        if deaths_today:
            death_text = f"昨晚死亡的玩家：{'、'.join(f'{d}号' for d in deaths_today)}"
        else:
            death_text = "昨晚是平安夜，无人死亡。"

        suspicions = self.memory.suspicion_summary()

        print(f"\n  ┌─ 🎤 发言环节 第{day}天 ────────────────────────────┐")
        print(f"  │ {death_text}")
        print(f"  │ 存活玩家：{self._alive_str(alive_ids)}")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        if suspicions and suspicions != "（暂无怀疑对象）":
            print(f"  │ 怀疑对象：{suspicions}")
        print(f"  └{'─' * 46}┘")

        while True:
            speech = await self._input("  💬 你的发言: ")
            if not speech.strip():
                fallbacks = ["我过。", "我是个普通村民，没什么信息，先听听大家的发言。",
                             "目前信息还不够，暂不发表意见。"]
                speech = random.choice(fallbacks)
            self.memory.add_speech(Speech(self.player_id, speech.strip(), day))
            return speech.strip()

    async def vote_decision(
        self,
        day: int,
        alive_ids: list[int],
        today_speeches: str,
        death_summary: str,
        recent_votes: str,
        private_info: str,
    ) -> Optional[int]:
        """Vote for elimination."""
        valid = [i for i in alive_ids if i != self.player_id]
        suspicions = self.memory.suspicion_summary()

        print(f"\n  ┌─ 🗳️ 投票放逐 第{day}天 ────────────────────────────┐")
        print(f"  │ {death_summary}")
        print(f"  │ 存活玩家：{self._alive_str(alive_ids)}")
        if private_info:
            for line in private_info.split("\n"):
                print(f"  │ {line}")
        if suspicions and suspicions != "（暂无怀疑对象）":
            print(f"  │ 怀疑对象：{suspicions}")
        print(f"  │ 可投票目标：{self._alive_str(valid)}（0 = 弃票）")
        print(f"  └{'─' * 46}┘")
        target = await self._input_choice("  请选择放逐目标编号 (0=弃票): ", valid, allow_zero=True)
        if target is not None:
            self.memory.add_vote(VoteRecord(self.player_id, target, day))
        return target


class WebHumanPlayer(HumanPlayer):
    """Human player whose decisions come from the web UI via DecisionAwaiter."""

    def __init__(self, player_id: int, role: Role, config: Config, awaiter: Any = None):
        super().__init__(player_id, role, config)
        self._awaiter = awaiter

    def _alive_list(self, alive_ids: list[int]) -> list[dict]:
        return [{"id": i, "label": f"玩家{i}号"} for i in alive_ids]

    # --- Night actions ---

    async def wolf_discussion_speak(
        self, night, alive_ids, recent_speeches, recent_votes,
        discussion_history, round_num, total_rounds, death_summary,
        wolf_kill_history="", past_discussions="",
    ) -> str:
        allies = self.memory.get_alive_werewolf_allies(alive_ids)
        return await self._awaiter.wait("wolf_discussion", {
            "night": night, "round": round_num, "total_rounds": total_rounds,
            "allies": [f"玩家{a}号" for a in allies],
            "death_summary": death_summary,
            "discussion_history": discussion_history,
            "valid_targets": self._alive_list(alive_ids),
        })

    async def werewolf_kill_decision(
        self, night, alive_ids, recent_speeches, recent_votes,
        discussion_summary, death_summary, wolf_kill_history="",
    ) -> Optional[int]:
        allies = self.memory.get_alive_werewolf_allies(alive_ids)
        return await self._awaiter.wait("wolf_kill", {
            "night": night,
            "allies": [f"玩家{a}号" for a in allies],
            "death_summary": death_summary,
            "discussion_summary": discussion_summary,
            "valid_targets": self._alive_list(alive_ids),
        })

    async def seer_check_decision(
        self, night, alive_ids, recent_speeches, recent_votes, death_summary="",
    ) -> Optional[int]:
        already_checked: set[int] = set()
        for entry in self.memory.check_results:
            import re
            nums = re.findall(r"\d+", entry)
            if nums:
                already_checked.add(int(nums[1]))
        valid = [i for i in alive_ids if i != self.player_id and i not in already_checked]
        if not valid:
            valid = [i for i in alive_ids if i != self.player_id]
        return await self._awaiter.wait("seer_check", {
            "night": night,
            "check_history": "\n".join(self.memory.check_results) if self.memory.check_results else "尚无查验记录",
            "valid_targets": self._alive_list(valid),
        })

    async def witch_night_decision(
        self, night, alive_ids, attacked_id, recent_speeches, recent_votes, death_summary="",
    ) -> tuple[str, Optional[int]]:
        result = await self._awaiter.wait("witch_decision", {
            "night": night,
            "attacked_id": attacked_id,
            "attacked_label": f"玩家{attacked_id}号" if attacked_id else "无人",
            "antidote_available": not self.memory.antidote_used,
            "poison_available": not self.memory.poison_used,
            "is_self_attacked": attacked_id == self.player_id and not self.memory.antidote_used,
            "alive_players": self._alive_list(alive_ids),
        })
        if isinstance(result, dict):
            return (result.get("action", "none"), result.get("target"))
        return ("none", None)

    async def hunter_shot_decision(
        self, alive_ids, death_cause, recent_speeches, recent_votes, death_summary="",
    ) -> int | None:
        valid = [i for i in alive_ids if i != self.player_id]
        return await self._awaiter.wait("hunter_shot", {
            "death_cause": death_cause,
            "valid_targets": self._alive_list(valid),
            "suspicions": self.memory.suspicion_summary(),
        })

    # --- Day actions ---

    async def sheriff_candidacy_decision(
        self, alive_ids, death_summary, private_info, current_candidates=None,
    ) -> bool:
        return await self._awaiter.wait("sheriff_candidacy", {
            "alive_players": self._alive_list(alive_ids),
            "death_summary": death_summary,
            "current_candidates": current_candidates or [],
            "private_info": private_info,
        })

    async def generate_campaign_speech(
        self, alive_ids, death_summary, private_info,
    ) -> str:
        speech = await self._awaiter.wait("campaign_speech", {
            "death_summary": death_summary,
            "private_info": private_info,
        })
        self.memory.add_speech(Speech(self.player_id, f"(竞选警长) {speech}", 1))
        return speech

    async def sheriff_withdraw_decision(
        self, candidates, campaign_speeches, private_info, death_summary="",
    ) -> bool:
        return await self._awaiter.wait("sheriff_withdraw", {
            "candidates": [{"id": c, "label": f"玩家{c}号"} for c in candidates],
            "campaign_speeches": {str(k): v for k, v in campaign_speeches.items()},
            "private_info": private_info,
        })

    async def sheriff_vote_decision(
        self, candidates, campaign_speeches, private_info, death_summary="",
    ) -> int | None:
        valid = [i for i in candidates if i != self.player_id]
        return await self._awaiter.wait("sheriff_vote", {
            "candidates": [{"id": c, "label": f"玩家{c}号"} for c in candidates],
            "valid_targets": self._alive_list(valid),
            "campaign_speeches": campaign_speeches,
            "private_info": private_info,
        })

    async def sheriff_destroy_badge_decision(
        self, alive_ids, recent_speeches, recent_votes, private_info,
    ) -> bool:
        return await self._awaiter.wait("sheriff_destroy_badge", {
            "alive_players": self._alive_list(alive_ids),
            "recent_speeches": recent_speeches,
            "recent_votes": recent_votes,
            "private_info": private_info,
        })

    async def sheriff_successor_decision(
        self, alive_ids, recent_speeches, recent_votes, private_info,
    ) -> int | None:
        valid = [i for i in alive_ids if i != self.player_id]
        return await self._awaiter.wait("sheriff_successor", {
            "valid_targets": self._alive_list(valid),
            "private_info": private_info,
        })

    async def generate_speech(
        self, day, alive_ids, deaths_today, recent_speeches, recent_votes, private_info,
    ) -> str:
        speech = await self._awaiter.wait("day_speech", {
            "day": day,
            "deaths_today": [f"玩家{d}号" for d in deaths_today] if deaths_today else [],
            "alive_players": self._alive_list(alive_ids),
            "private_info": private_info,
            "suspicions": self.memory.suspicion_summary(),
        })
        if not speech or not speech.strip():
            speech = random.choice(["我过。", "我是个普通村民，没什么信息，先听听大家的发言。",
                                     "目前信息还不够，暂不发表意见。"])
        self.memory.add_speech(Speech(self.player_id, speech.strip(), day))
        return speech.strip()

    async def vote_decision(
        self, day, alive_ids, today_speeches, death_summary, recent_votes, private_info,
    ) -> Optional[int]:
        valid = [i for i in alive_ids if i != self.player_id]
        target = await self._awaiter.wait("elimination_vote", {
            "day": day,
            "death_summary": death_summary,
            "valid_targets": self._alive_list(valid),
            "private_info": private_info,
            "suspicions": self.memory.suspicion_summary(),
        })
        if target is not None:
            self.memory.add_vote(VoteRecord(self.player_id, target, day))
        return target
