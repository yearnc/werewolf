"""Memory management for AI players.

Each AI player maintains a sliding window of recent speeches, votes, and
private knowledge (e.g. seer check results, werewolf allies).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Speech:
    player_id: int
    content: str
    day: int


@dataclass
class VoteRecord:
    voter_id: int
    target_id: int
    day: int


@dataclass
class PlayerMemory:
    player_id: int
    role: str  # The player's own role (in Chinese)
    werewolf_allies: list[int] = field(default_factory=list)
    speeches: list[Speech] = field(default_factory=list)
    votes: list[VoteRecord] = field(default_factory=list)
    sheriff_votes: list[VoteRecord] = field(default_factory=list)
    deaths: list[dict] = field(default_factory=list)
    check_results: list[str] = field(default_factory=list)
    suspicions: dict[int, str] = field(default_factory=dict)  # target_id -> reason
    antidote_used: bool = False
    poison_used: bool = False

    def add_speech(self, speech: Speech) -> None:
        self.speeches.append(speech)
        # Keep last 3 days
        current_day = speech.day
        self.speeches = [s for s in self.speeches if s.day >= current_day - 2]

    def add_vote(self, vote: VoteRecord) -> None:
        self.votes.append(vote)
        current_day = vote.day
        self.votes = [v for v in self.votes if v.day >= current_day - 2]
        # Auto-record suspicion based on vote target
        if vote.target_id not in self.suspicions:
            self.suspicions[vote.target_id] = f"第{vote.day}天投票放逐"

    def add_sheriff_vote(self, vote: VoteRecord) -> None:
        self.sheriff_votes.append(vote)

    def add_suspicion(self, target_id: int, reason: str) -> None:
        self.suspicions[target_id] = reason

    def remove_suspicion(self, target_id: int) -> None:
        self.suspicions.pop(target_id, None)

    def suspicion_summary(self) -> str:
        if not self.suspicions:
            return "（暂无怀疑对象）"
        lines = []
        for tid, reason in self.suspicions.items():
            lines.append(f"怀疑 玩家{tid}号：{reason}")
        return "\n".join(lines)

    def add_death(self, player_id: int, day: int) -> None:
        self.deaths.append({"player_id": player_id, "day": day})
        # Dead players can no longer be suspects
        self.suspicions.pop(player_id, None)

    def add_check_result(self, target_id: int, is_werewolf: bool, night: int) -> None:
        result = "狼人" if is_werewolf else "好人"
        self.check_results.append(f"第{night}夜查验玩家{target_id}号：{result}")

    def recent_speeches(self, current_day: int) -> str:
        recent = [s for s in self.speeches if s.day >= current_day - 2]
        if not recent:
            return "（暂无发言记录）"
        return "\n".join(f"玩家{s.player_id}号：{s.content}" for s in recent)

    def recent_votes(self, current_day: int) -> str:
        recent = [v for v in self.votes if v.day >= current_day - 2]
        if not recent:
            return "（暂无投票记录）"
        return "\n".join(f"玩家{v.voter_id}号 → 投票放逐 玩家{v.target_id}号" for v in recent)

    def today_speeches(self, day: int) -> str:
        today = [s for s in self.speeches if s.day == day]
        if not today:
            return "（今日尚无发言）"
        return "\n".join(f"玩家{s.player_id}号：{s.content}" for s in today)

    def get_alive_werewolf_allies(self, alive_ids: list[int]) -> list[int]:
        return [a for a in self.werewolf_allies if a in alive_ids]

    def summary(self) -> str:
        lines = [
            f"=== 玩家{self.player_id}号 记忆 ===",
            f"身份：{self.role}",
        ]
        if self.werewolf_allies:
            lines.append(f"狼队友：{self.werewolf_allies}")
        if self.check_results:
            lines.append("查验记录：")
            for c in self.check_results:
                lines.append(f"  {c}")
        lines.append(f"解药：{'已用' if self.antidote_used else '未用'}")
        lines.append(f"毒药：{'已用' if self.poison_used else '未用'}")
        if self.suspicions:
            lines.append("怀疑对象：")
            for tid, reason in self.suspicions.items():
                lines.append(f"  玩家{tid}号：{reason}")
        if self.sheriff_votes:
            lines.append("警长竞选投票：")
            for v in self.sheriff_votes:
                lines.append(f"  玩家{v.voter_id}号 → 玩家{v.target_id}号")
        lines.append(f"\n发言记录（{len(self.speeches)}条）：")
        for s in self.speeches[-10:]:
            lines.append(f"  Day{s.day} P{s.player_id}: {s.content[:60]}...")
        lines.append(f"\n投票记录（{len(self.votes)}条）：")
        for v in self.votes[-10:]:
            lines.append(f"  Day{v.day} P{v.voter_id} → P{v.target_id}")
        lines.append(f"\n死亡记录：{self.deaths}")
        return "\n".join(lines)
