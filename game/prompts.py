"""Prompt templates for LLM calls.

All prompts are in Chinese since the game is played in Chinese.
Each function returns a (system_prompt, user_prompt) tuple.
"""

from __future__ import annotations

from role import ROLE_ABILITY, ROLE_DISPLAY, Role, get_team_display


def build_system_prompt(player_id: int, role: Role) -> str:
    role_name = ROLE_DISPLAY[role]
    team = get_team_display(role)
    ability = ROLE_ABILITY[role]

    return f"""你是玩家{player_id}号，你的身份是 **{role_name}**，属于{team}。
{ability}

## 游戏规则
- 9人局：3狼人、1预言家、1女巫、1猎人、3村民
- 夜晚：狼人击杀一名玩家 → 预言家查验身份 → 女巫选择用药（狼人不能空刀，必须选择击杀目标）
- 白天：宣布死者 → 轮流发言 → 投票放逐一名玩家
- 猎人：被投票放逐或狼人击杀时可开枪带走一名玩家（被毒杀则不能开枪）
- 狼人阵营胜利条件：屠边（杀死所有村民 或 杀死所有神职），或当狼人存活人数 ≥ 好人存活人数时直接获胜
- 好人阵营胜利条件：放逐所有狼人

## 行为准则
- 用中文发言，2-4句话，充分表达推理，不要长篇大论
- 基于你的角色视角推理，不要暴露你是AI
- ⚠️ 发言前先看前面的人说了什么！不要机械重复别人已经说过的观点。如果3个以上的人都在说同一件事，你再重复一遍会显得很不自然。正确做法：如果认同前面的分析，一句话带过（"我同意前面几位对X号的判断"），然后补充新视角、质疑遗漏的疑点、或提出不同的推理方向。好的发言是层层推进的，不是每个人都从零开始重新说一遍
- 投票时理性分析，不要随机乱投
- 发言中直接说内容，不要加"玩家X号："之类的前缀
- 如果你是狼人：伪装成好人，避免被识破，注意配合狼队友的发言。你知道所有狼队友是谁——不在狼队友列表中的玩家绝对不是狼人，在狼人讨论时不要称他们为"悍跳狼"
- 如果你是预言家：查到狼人应尽早跳身份报查验；若多轮查到好人且无人对跳，可继续隐藏
- 如果你是女巫：关键时刻可跳身份报用药信息。第一晚一般用解药救人。毒药只有一瓶且不可逆，只毒能确定是狼的目标
- 如果你是猎人：前期隐藏身份，被怀疑时可跳明身份自证
- 如果你是村民：积极分析发言逻辑，找出逻辑漏洞，提出怀疑对象
- 如果你是警长：你是最后一个发言的人，你发言结束后直接进入投票环节，不会有人再发言。因此你必须做出最终决断——指定一个明确的归票目标让大家统一投票，或号召弃票。不要说"让X号再解释一下""等X号发言后再看""听听X号怎么说"这类话，因为没有人会在你之后发言了"""


def build_speak_prompt(
    player_id: int,
    role: Role,
    day: int,
    alive_ids: list[int],
    death_text: str,
    recent_speeches: str,
    recent_votes: str,
    private_info: str,
    suspicions: str,
) -> str:
    role_name = ROLE_DISPLAY[role]

    return f"""## 当前局势
现在是第{day}天白天。{death_text}

## 存活玩家（{len(alive_ids)}人）
{', '.join(f'玩家{i}号' for i in alive_ids)}

## 近期发言
{recent_speeches}
⚠️ 发言要有差异性：前面的人已经说了哪些观点？不要机械重复已被反复提及的信息。跳过共识，直接进入你的独特分析。如果你的发言和前一个人几乎一样，说明你没有独立思考。

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

{private_info}

请以玩家{player_id}号（{role_name}）的身份发言。根据你的角色定位和当前局势，发表2-3句有逻辑的发言，说明你的推理和判断。
- 如果怀疑某人，明确指出并说明理由
- 如果是预言家：查到了狼人应果断跳身份报查验；查到好人且局势安全可先隐藏
- 如果是女巫且需要报用药信息，可以跳身份说明
- 如果是狼人：注意伪装，可以适当跟风或反咬，但发言要自然不刻意
- 如果你是警长：你是最后一个发言的人，你的发言结束就立即投票。你必须做出最终决断——给出明确的归票目标（说"今天归票X号"），或号召弃票。严禁说"让X号再解释一下""听听X号怎么说""等X号发言后再判断"——你后面没人了，没有"再"的机会
- 直接说发言内容，不要加"玩家X号："的前缀，用中文，不要使用特殊格式
⚠️ 绝对不要在发言中透露任何"私密信息"标签下的内容！
⚠️ 【禁止幻觉】只引用上方「近期发言」中实际存在的内容。如果某个玩家在「近期发言」里没有记录，说明他还没有发过言，不要凭空编造"X号说过XX"。不确定就说"不确定"。"""


def build_vote_prompt(
    player_id: int,
    role: Role,
    day: int,
    alive_ids: list[int],
    today_speeches: str,
    death_summary: str,
    recent_votes: str,
    private_info: str,
    suspicions: str,
) -> str:
    alive_list = ", ".join(f"{i}号" for i in alive_ids)

    return f"""## 投票环节 - 第{day}天

## 当前局势
{death_summary}

## 本轮发言总结
{today_speeches}

## 存活玩家
{alive_list}

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

{private_info}

请从存活玩家中选择一个你要投票放逐的人。仔细分析今天的发言，做出最合理的判断。
投票前请思考：今天谁的发言前后矛盾？谁在跟风没有自己的判断？谁在刻意引导风向？谁的反应与自己的角色不符？
如果你认为当前没有足够理由放逐任何人，可以回复 0 选择弃票。
注意：警长拥有1.5票，如果你自己是警长，你的投票权重更大。
⚠️ 【禁止幻觉】只基于上方「本轮发言总结」中实际出现的内容做判断。不要编造某人说了什么话。
**只回复一个玩家编号数字（或 0 表示弃票）**，不要回复任何其他内容。

可投票的玩家编号：{[i for i in alive_ids if i != player_id]}（0 = 弃票）
你的投票目标（只回复数字）："""


def build_werewolf_night_prompt(
    player_id: int,
    night: int,
    alive_ids: list[int],
    werewolf_allies: list[int],
    recent_speeches: str,
    recent_votes: str,
    discussion_summary: str,
    death_summary: str,
    suspicions: str = "",
    wolf_kill_history: str = "",
    dead_ids: list[int] | None = None,
) -> str:
    allies_str = ", ".join(f"{a}号" for a in werewolf_allies) if werewolf_allies else "无"
    alive_str = ", ".join(f"{i}号" for i in alive_ids)

    dead_warning = ""
    if dead_ids:
        dead_str = "、".join(f"{d}号" for d in dead_ids)
        dead_warning = f"\n⚠️ 已死亡玩家（无法击杀）：{dead_str}"

    return f"""## 夜晚行动 - 狼人击杀

你是玩家{player_id}号（狼人）。现在是第{night}夜。

## 当前局势
{death_summary}
{dead_warning}

{wolf_kill_history}

## 你的狼队友
{allies_str}

## 存活玩家
{alive_str}

## 近期发言
{recent_speeches}

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

## 今晚狼队友讨论总结
{discussion_summary}

请根据讨论结果选择今晚的击杀目标。优先考虑击杀神职角色，但也要尊重多数狼队友的意见。
⚠️ 【禁止幻觉】只能从上方「存活玩家」列表中选择目标。已死亡玩家无法被击杀。不要击杀狼队友（除非队友一致同意自刀）。
**只回复一个玩家编号数字**，不要回复任何其他内容。
{("（战术提示：首夜可以考虑自刀骗女巫解药做身份，但风险较高。）" if night == 1 else "")}

存活玩家编号：{alive_ids}
击杀目标（只回复数字）："""


def build_wolf_discussion_prompt(
    player_id: int,
    night: int,
    werewolf_allies: list[int],
    alive_ids: list[int],
    recent_speeches: str,
    recent_votes: str,
    discussion_history: str,
    round_num: int,
    total_rounds: int,
    death_summary: str,
    suspicions: str = "",
    wolf_kill_history: str = "",
    past_discussions: str = "",
    dead_ids: list[int] | None = None,
) -> str:
    allies_str = ", ".join(f"{a}号" for a in werewolf_allies) if werewolf_allies else "无"
    alive_str = ", ".join(f"{i}号" for i in alive_ids)

    dead_warning = ""
    if dead_ids:
        dead_str = "、".join(f"{d}号" for d in dead_ids)
        dead_warning = f"\n⚠️ 已死亡玩家（绝对不能刀，也无需讨论刀他们）：{dead_str}\n"

    return f"""## 狼人讨论 - 第{night}夜（第{round_num}/{total_rounds}轮）

你是玩家{player_id}号（狼人）。现在是夜间讨论环节，你和狼队友在商议今晚击杀目标。

## 当前局势
{death_summary}

{wolf_kill_history}

{past_discussions}

## 你的狼队友
{allies_str}

## 存活玩家（可击杀目标）
{alive_str}{dead_warning}

## 近期白天发言
{recent_speeches}

## 近期投票
{recent_votes}

## 本轮讨论记录
{discussion_history if discussion_history else "（讨论刚开始）"}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

请发表你的意见。简短有力（2-3句话），讨论应该围绕：
- 分析谁最可能是神职（预言家、女巫、猎人）
- 建议击杀目标及理由
- 回应狼队友的建议
- 目标是达成一致意见，认真考虑队友的建议，必要时做出妥协

⚠️ 重要：你知道所有狼队友是谁。不在"你的狼队友"列表中的玩家**绝对不是狼人**。
- 如果有人跳预言家且不是你的狼队友 → 他要么是真预言家，要么是穿衣服的村民，**不要说他是"悍跳狼"**
- 只能用"悍跳"来形容你自己的狼队友（因为他们才是狼）
- 正确说法示例："5号不是我们的人却跳预言家，可能是真预言家"
⚠️ 【禁止幻觉】只基于上方提供的实际游戏信息讨论。不要编造没有发生的事件。如果有人提议刀已死亡的玩家，务必指出并纠正。不确定就说"不确定"。"""


def build_seer_night_prompt(
    player_id: int,
    night: int,
    alive_ids: list[int],
    check_history: str,
    recent_speeches: str,
    recent_votes: str,
    death_summary: str = "",
    suspicions: str = "",
    dead_ids: list[int] | None = None,
) -> str:
    alive_str = ", ".join(f"{i}号" for i in alive_ids)

    dead_warning = ""
    if dead_ids:
        dead_str = "、".join(f"{d}号" for d in dead_ids)
        dead_warning = f"\n⚠️ 已死亡玩家（无法查验）：{dead_str}"

    return f"""## 夜晚行动 - 预言家查验

你是玩家{player_id}号（预言家）。现在是第{night}夜。

## 死亡记录
{death_summary}

## 你的查验记录
{check_history}
（已查验过的玩家不要重复查验，查验他们不会获得新信息）

## 存活玩家
{alive_str}{dead_warning}

## 近期发言
{recent_speeches}

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

请选择今晚要查验的玩家。优先查验发言可疑或行为异常的玩家，其次是查验那些身份不明确的玩家。
⚠️ 【禁止幻觉】只能从上方「存活玩家」列表中选择。不要查验已死亡玩家或自己。不要重复查验已有结果的玩家。
**只回复一个玩家编号数字**，不要回复任何其他内容。

存活玩家编号：{alive_ids}
查验目标（只回复数字）："""


def build_witch_night_prompt(
    player_id: int,
    night: int,
    alive_ids: list[int],
    attacked_id: int | None,
    antidote_available: bool,
    poison_available: bool,
    recent_speeches: str,
    recent_votes: str,
    death_summary: str = "",
    suspicions: str = "",
) -> str:
    alive_str = ", ".join(f"{i}号" for i in alive_ids)
    death_info = f"玩家{attacked_id}号" if attacked_id else "无人被杀"
    antidote_status = "可用" if antidote_available else "已用"
    poison_status = "可用" if poison_available else "已用"

    self_hint = ""
    if attacked_id is not None and attacked_id == player_id and antidote_available:
        self_hint = "\n⚠️ 注意：今晚狼人的击杀目标就是你自己！你可以在本轮使用解药自救。"

    waste_warning = ""
    if attacked_id is not None and not antidote_available:
        waste_warning = (
            f"\n⚠️ 重要提醒：你的解药已用，狼人今晚击杀的 玩家{attacked_id}号 已经死亡。"
            f"毒药应该用来毒杀其他存活的嫌疑人，绝对不要毒 玩家{attacked_id}号（已经死了，毒了白费）！"
        )

    return f"""## 夜晚行动 - 女巫用药

你是玩家{player_id}号（女巫）。现在是第{night}夜。

## 死亡记录
{death_summary}

## 今晚情况
今晚狼人击杀的目标：{death_info}{self_hint}{waste_warning}

## 你的药水
- 解药：{antidote_status}
- 毒药：{poison_status}

## 存活玩家
{alive_str}

## 近期发言
{recent_speeches}

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

请决定今晚使用哪种药水（每夜最多使用一瓶）。根据当前局势做出最优选择。
- 如果被刀的是你自己或关键神职，优先使用解药救人（包括自救）
{("- 第" + str(night) + "夜了，解药越早用越划算，考虑是否用解药救人" if night <= 2 and antidote_available else "")}{("- 解药如果还没用，建议尽早用掉" if night > 2 and antidote_available else "")}

⚠️ 毒药使用原则（毒药只有一瓶，不可逆，必须谨慎）：
- 毒药是用来消灭**确定是狼人**的目标，不是用来毒"可疑"的人
- 毒跳预言家的人之前要仔细判断：如果他被真预言家发了查杀、或发言前后矛盾、或有多人站边他且站边者行为像狼，才可能是悍跳狼
- 不要因为单纯怀疑就毒预言家——毒错真预言家等于帮狼人赢
- 只有当你几乎确定某人是狼人时（如被真预言家发了查杀、发言明显自相矛盾、行为完全像狼），才考虑使用毒药
- 如果没有足够把握，回复 "none" 保留毒药等待更明确的时机
⚠️ 【禁止幻觉】只能从上方「存活玩家」列表中选择毒药目标。已死亡的玩家无法被毒。不要编造某人被查杀或发言矛盾等不实信息。
- 回复 "save" 使用解药救人
- 回复 "poison X" 使用毒药毒玩家X号（X为数字）
- 回复 "none" 不使用任何药水

你的决定："""


def build_hunter_shot_prompt(
    player_id: int,
    alive_ids: list[int],
    death_cause: str,
    recent_speeches: str,
    recent_votes: str,
    suspicions: str,
    death_summary: str = "",
    dead_ids: list[int] | None = None,
) -> str:
    alive_str = ", ".join(f"{i}号" for i in alive_ids)

    dead_warning = ""
    if dead_ids:
        dead_str = "、".join(f"{d}号" for d in dead_ids)
        dead_warning = f"\n⚠️ 已死亡玩家（无法射击）：{dead_str}"

    return f"""## 猎人开枪

你是玩家{player_id}号（猎人）。你因为{death_cause}即将死亡。

根据你的技能，你可以在临死前开枪带走一名玩家同归于尽。

## 死亡记录
{death_summary}

## 存活玩家（可射击目标）
{alive_str}{dead_warning}

## 近期发言
{recent_speeches}

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

请选择一个你要带走的玩家。这是不可逆的决定，请仔细回顾整局游戏中每个人的发言和投票行为，找出最有可能是狼人的那个人。
- 回顾谁的发言前后矛盾
- 回顾谁在关键投票中的行为异常
- 回顾谁在被怀疑时的反应不像好人
⚠️ 【禁止幻觉】只能从上方「存活玩家」列表中选择目标。不要射击自己。不要射击已死亡的玩家。
**只回复一个玩家编号数字**，不要回复任何其他内容。

存活玩家编号：{[i for i in alive_ids if i != player_id]}
你的射击目标（只回复数字）："""


def build_sheriff_candidacy_prompt(
    player_id: int,
    role: Role,
    alive_ids: list[int],
    death_summary: str,
    private_info: str,
    current_candidates: list[int] | None = None,
) -> str:
    role_name = ROLE_DISPLAY[role]
    alive_str = ", ".join(f"{i}号" for i in alive_ids)

    candidates_info = ""
    if current_candidates:
        candidates_str = "、".join(f"{c}号" for c in current_candidates)
        candidates_info = f"\n## 已报名参选的玩家\n{candidates_str}\n"
    elif current_candidates is not None:
        candidates_info = "\n## 已报名参选的玩家\n（暂时无人报名）\n"

    return f"""## 警长竞选 - 报名

你是玩家{player_id}号（{role_name}）。现在是警长竞选报名环节，你可以选择是否参加警长竞选。

## 当前局势
存活玩家（{len(alive_ids)}人）：{alive_str}
{death_summary}{candidates_info}
{private_info}

注意：如果参加竞选，你将失去投票权（不能投票选警长）；如果不参加，你可以投票选警长。
战略提示：预言家参选可通过警徽传递查验信息；狼人参选可争夺警徽控制归票；村民参选可帮好人阵营掌握主动权。
请根据你的角色和局势决定是否参选。
- 回复 "run" 参加竞选
- 回复 "pass" 不参加
⚠️ 只回复 "run" 或 "pass"，不要回复其他内容。

你的决定："""


def build_sheriff_campaign_prompt(
    player_id: int,
    role: Role,
    alive_ids: list[int],
    death_summary: str,
    private_info: str,
) -> str:
    role_name = ROLE_DISPLAY[role]
    return f"""## 警长竞选 - 竞选发言

你是玩家{player_id}号（{role_name}）。现在是警长竞选环节。

## 当前局势
存活玩家（{len(alive_ids)}人）：{', '.join(f'{i}号' for i in alive_ids)}
{death_summary}

{private_info}

请你发表一段竞选发言，说明你为什么要当警长、你当上警长后的计划。
- 如果你是神职（预言家、女巫、猎人），可以考虑暗示身份争取信任
- 如果是狼人，伪装成好人争取警徽
发言要简短（1-2句话），用中文。
⚠️ 【禁止幻觉】不要编造查验结果、用药信息等你不可能知道的内容。基于你的真实角色发言。

你的竞选发言："""


def build_sheriff_withdraw_prompt(
    player_id: int,
    role: Role,
    candidates: list[int],
    campaign_speeches: dict[int, str],
    private_info: str,
    death_summary: str = "",
) -> str:
    """Prompt for deciding whether to withdraw from sheriff election."""
    other_candidates = [c for c in candidates if c != player_id]
    other_list = ", ".join(f"{c}号" for c in other_candidates) if other_candidates else "无"
    speeches_text = "\n".join(f"玩家{pid}号：{s}" for pid, s in campaign_speeches.items())

    return f"""## 警长竞选 - 退水决定

你是玩家{player_id}号，当前正在参与警长竞选。

## 当前局势
{death_summary}

## 所有竞选发言
{speeches_text}

## 当前仍在警上的候选人
{'、'.join(f'{c}号' for c in candidates)}

## 其他候选人
{other_list}

{private_info}

请决定是否退出警长竞选（退水）。考虑以下因素：
- 你的发言是否有说服力，能否赢得其他玩家的信任
- 其他候选人的发言质量如何，是否比你更值得当选
- 如果你是狼人，是否需要隐藏身份；如果你有强身份，是否需要警徽
- 如果没有人退水会导致票数分散，适当退水可以集中票数

回复 with word "withdraw" 表示退水，回复 "stay" 表示留在警上。
**只回复一个单词 (withdraw 或 stay)**："""


def build_sheriff_vote_prompt(
    player_id: int,
    role: Role,
    candidates: list[int],
    campaign_speeches: str,
    private_info: str,
    suspicions: str,
    death_summary: str = "",
) -> str:
    """Prompt for voting for sheriff."""
    candidate_list = ", ".join(f"{i}号" for i in candidates)

    return f"""## 警长竞选 - 投票

你是玩家{player_id}号。请根据以下竞选发言，选择一名玩家作为警长。

## 当前局势
{death_summary}

## 竞选发言
{campaign_speeches}

## 候选人
{candidate_list}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

{private_info}

请选择一个你认为最适合当警长的玩家。警长拥有1.5票投票权并且始终在最后一个发言（可以总结全场），因此警长人选对游戏走向至关重要。优先选择发言有逻辑、行为像队友的玩家。
⚠️ 【禁止幻觉】只基于上方「竞选发言」中实际出现的内容做判断。不要编造某人的发言内容。
**只回复一个玩家编号数字**，不要回复任何其他内容。

候选人编号：{candidates}
你的警长投票（只回复数字）："""


def build_sheriff_destroy_badge_prompt(
    player_id: int,
    role: Role,
    alive_ids: list[int],
    recent_speeches: str,
    recent_votes: str,
    private_info: str,
) -> str:
    """Prompt for dying sheriff to decide whether to destroy the badge."""
    alive_list = ", ".join(f"{i}号" for i in alive_ids)

    return f"""## 警长死亡 - 撕警徽决定

你是玩家{player_id}号（警长）。你即将死亡。

在移交警徽之前，你可以选择**撕毁警徽**（销毁），这意味着本局将不再有警长。

## 存活玩家
{alive_list}

## 近期发言
{recent_speeches}

## 近期投票
{recent_votes}

{private_info}

请决定是撕毁警徽还是移交警徽。考虑以下因素：
- 如果你没有信任的玩家，或者不想让对方阵营通过继承警徽获利，可以考虑撕毁
- 如果你有明确信任的队友，交给他可以增加阵营的投票权重（警长1.5票+最后发言）
- 撕毁警徽意味着1.5票权重和最后发言权永久消失

回复 "destroy" 表示撕毁警徽，回复 "pass" 表示移交警徽。
**只回复一个单词 (destroy 或 pass)**："""


def build_sheriff_successor_prompt(
    player_id: int,
    alive_ids: list[int],
    recent_speeches: str,
    recent_votes: str,
    suspicions: str,
    private_info: str,
) -> str:
    """Prompt for dying sheriff to choose a successor."""
    alive_list = ", ".join(f"{i}号" for i in alive_ids)

    return f"""## 警长移交警徽

你是玩家{player_id}号（警长）。你即将死亡，需要将警徽移交给一名存活玩家。

## 存活玩家
{alive_list}

## 近期发言
{recent_speeches}

## 近期投票
{recent_votes}

## 你的怀疑对象（仅供参考，请独立判断）
{suspicions}

{private_info}

请选择一个你信任的玩家来接任警长。优先考虑你认为传递后局势对你所在阵营有利的玩家。
⚠️ 【禁止幻觉】只能从上方「存活玩家」列表中选择。不要编造不存在的发言作为移交理由。
**只回复一个玩家编号数字**，不要回复任何其他内容。

可移交的玩家编号：{[i for i in alive_ids if i != player_id]}
你的选择（只回复数字）："""
