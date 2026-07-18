# Subagent CC 閫愰」瀵规瘮

> Canonical status:
> - This is the canonical comparison document for Subagent alignment work.
> - Pair it with `docs/v2-react-architecture.md` for the current verified runtime shape.
> - When historical docs disagree, prefer this document and the verified architecture doc.

> Status update (2026-07-17):
> - Gap 1 is partially outdated: `AUTO` placement is no longer resolved only from
>   `definition.background`. `agent/session/task_tool.py` already applies typed
>   runtime facts on top of `AgentSpawnRequest.resolve_execution_placement()`,
>   including fan-out width and worktree isolation. The remaining work is to
>   make this policy more explicit and fully declarative, not to introduce the
>   idea for the first time.
> - Gap 2 is partially outdated: the Runtime already has a typed `_ChildTurnPhase`
>   overlay (`NONE` / `SYNTHESIS` / `RESOLUTION_PENDING`) in `agent/core.py`.
>   The remaining work is to strengthen the phase discipline, not to invent it.
> - Gap 3 is partially outdated: the typed child-control surface is already split
>   into `SendMessage`, `WaitForAgent`, and `CancelAgent`. `agent_control` is now
>   primarily a compatibility wrapper.
> - Gap 5 is partially outdated: nested delegation is already routed through the
>   declarative `DelegationPolicy` + `permits_subagent()` path. The remaining work
>   is mostly clarity and removal of stale historical wording.
> - Read the detailed gap sections below as historical design analysis unless they
>   are consistent with the current code and `docs/v2-react-architecture.md`.

> 鏃ユ湡锛?026-07-17
> 瀵圭収鍩虹嚎锛歚docs/plan-mode-comparison.md`
> 鐩爣锛氭妸 forge-agent 褰撳墠鐨?Subagent / Fork / Fan-out / Resume / Synthesis 涓婚摼锛?> 鍜?Claude Code 鍏紑璁捐鎬濊矾閫愰」瀵归綈锛屽舰鎴愬悗缁垎鎵规敼閫犺鍒掋€?
---

## 鎴戜滑鐨勫畬鏁?Subagent 娴佺▼锛堥€愬嚱鏁拌拷韪級

### 闃舵 1锛氱埗浠ｇ悊鏆撮湶鍙娲捐兘鍔?
```text
agent/session/runtime.py:538  run_session()
  鈫?agent/session/agent_factory.py  鍒涘缓褰撳墠 session 瀵瑰簲鐨?ReActAgent
  鈫?agent/session/registry_builder.py:72  build_registry_for_session()
    鈫?attach_delegation_tools(...)
      鈫?娉ㄥ唽 Agent
      鈫?娉ㄥ唽 agent_control
      鈫?濡傛湁 worktree 瀛愪唬鐞嗭紝鍐嶆敞鍐?worktree review tools
  鈫?agent/session/runtime_prompt_builder.py:19  build_runtime_messages()
    鈫?娉ㄥ叆 Available Subagents
    鈫?娉ㄥ叆 fresh-context / worktree / fan-out / synthesis 鐩稿叧鎻愮ず
```

**鍏抽敭浠ｇ爜**

- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:538>)
- [agent/session/registry_builder.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/registry_builder.py:72>)
- [agent/session/runtime_prompt_builder.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime_prompt_builder.py:19>)

### 闃舵 2锛氱埗浠ｇ悊璋冪敤 Agent 宸ュ叿

```text
agent/session/task_tool.py:74  class AgentTool
  鈫?parameters: subagent_type / description / prompt / execution_placement / isolation
  鈫?concurrency_mode(): 鍙厑璁糕€滃叡浜伐浣滃尯 + 鍙鈥濅换鍔″苟琛?fan-out
  鈫?execute():
      1. 鏍￠獙 subagent_type 鏄惁鍦?declarative allowlist 涓?      2. 瑙ｆ瀽 named vs fork
      3. 瑙ｆ瀽 execution_placement (AUTO / FOREGROUND / BACKGROUND)
      4. named: _build_subagent_prompt() 鍖呰鏈€灏?_SUBAGENT_PROTOCOL
      5. fork: 鐩存帴淇濈暀 delta prompt锛屼娇鐢ㄧ埗蹇収
      6. 璋冪敤 runtime.spawn_agent(...)
```

**鍏抽敭浠ｇ爜**

- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:74>)
- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:125>)
- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:600>)

### 闃舵 3锛歊untime 鐢熸垚 typed child contract

```text
agent/session/models.py:555  AgentSpawnRequest
  鈫?identity/context/workspace/placement 姝ｄ氦鍖?  鈫?named:
      fresh context
      definition.background => AUTO 鏃惰В鏋愪负 BACKGROUND
  鈫?fork:
      parent snapshot
      榛樿 foreground锛岄櫎闈炴樉寮忔寚瀹?background

agent/session/runtime.py:732  spawn_agent()
  鈫?楠岃瘉 direct parent / max depth / delegation grant
  鈫?named child:
      definition 鏉ヨ嚜 registry
  鈫?fork child:
      spawn_context 蹇呴』瀛樺湪锛屾ā鍨嬪悕 / schema snapshot 蹇呴』涓€鑷?  鈫?create_session(...)
  鈫?璁板綍 parent_snapshot_fingerprint / parent_tool_schemas / parent_policy
  鈫?foreground: 鐩存帴鎵ц
  鈫?background: _start_background_execution()
```

**鍏抽敭浠ｇ爜**

- [agent/session/models.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/models.py:555>)
- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:732>)

### 闃舵 4锛欳hild 缁撴灉杩斿洖鐖朵唬鐞?
```text
foreground child
  鈫?AgentTool.execute() 鐩存帴鎷垮埌 AgentRunResult
  鈫?_format_fork_result() 娓叉煋涓?<task-notification>
  鈫?浣滀负 observation 鍥炲埌鐖?ReAct loop

background child
  鈫?runtime._start_background_execution()
    鈫?child 缁撴潫鍚?append_agent_notification(...)
  鈫?涓嬩竴杞埗浠ｇ悊 run 寮€濮嬫椂
    鈫?runtime._claim_completion_messages()
    鈫?claim_agent_completions()
    鈫?_project_completion_notifications()
    鈫?浣滀负 user 娑堟伅娉ㄥ叆 <task-notification>
```

**鍏抽敭浠ｇ爜**

- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1388>)
- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1398>)
- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:500>)

### 闃舵 5锛氱埗浠ｇ悊缁煎悎锛坧ost-child synthesis锛?
```text
agent/core.py
  姣忚疆寮€濮嬶細
    鈫?runtime_message_source() 鍙兘娉ㄥ叆 background <task-notification>
    鈫?鑻ユ湰杞垰鏀跺埌 child completion:
        _has_child_completion_notifications(...)
        _without_new_agent_spawns(...)
        => 鏆傛椂鎾ゆ帀鏂扮殑 Agent 娲惧彂

  宸ュ叿鎵ц鍚庯細
    鈫?鑻ユ湰杞?observation 涓嚭鐜?foreground <task-notification>
        _observations_include_child_notifications(...)
        => 涓嬩竴杞悓鏍疯繘鍏?post-child synthesis turn
```

涔熷氨鏄锛屾垜浠幇鍦ㄥ凡缁忔湁涓€涓?*鏈€灏忕湡瀹炵増** post-child synthesis锛?
- child 缁撴灉涓€鍒?- 涓嬩竴杞厛鎾ゆ帀鏂扮殑 `Agent`
- 浣嗕繚鐣?`agent_control` / worktree review / 鏅€氳鍐欓獙璇佸伐鍏?
**鍏抽敭浠ｇ爜**

- [agent/core.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:90>)
- [agent/core.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:100>)
- [agent/core.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:110>)

### 闃舵 6锛欳hild 鎺у埗闈?
```text
agent/session/agent_control_tool.py:32  AgentControlTool
  action=message  鈫?send_agent_message()
  action=wait     鈫?wait_for_agent()
  action=cancel   鈫?cancel_agent()
```

褰撳墠瀹冩槸涓€涓仛鍚堟帶鍒堕潰锛岃€屼笉鏄?Claude Code 閭ｇ鏇存樉寮忔媶鍒嗙殑澶氳兘鍔涢潰銆?
**鍏抽敭浠ｇ爜**

- [agent/session/agent_control_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/agent_control_tool.py:32>)
- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1145>)
- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1272>)

### 闃舵 7锛欳hat / Skill fork 鍏ュ彛

```text
entry/chat.py:457  _run_skill_fork()
  鈫?_create_skill_fork_runtime_session()
  鈫?runtime.create_root_session(...)
  鈫?runtime.spawn_agent(AgentSpawnRequest.named(...))
```

杩欎竴鏉″凡缁忎笉鍐嶈蛋鎵嬫悡 agent.run 鍒嗘敮锛岃€屾槸骞跺洖 Runtime 涓婚摼銆?
**鍏抽敭浠ｇ爜**

- [entry/chat.py](</D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:457>)
- [entry/chat.py](</D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:518>)

---

## Claude Code 鐨?Subagent 鍏紑璁捐锛堟寜鍏紑璧勬枡鏁寸悊锛?
### 闃舵 1锛歋ubagent 鏄厤缃寲鍘熺敓鑳藉姏

Claude Code 瀹樻柟鏂囨。鏄庣‘鎶?Subagents 浣滀负涓€绛夎兘鍔涳細

- 瀛愪唬鐞嗘湁鍚嶅瓧銆佹弿杩般€佸伐鍏枫€佺郴缁熸彁绀恒€佹ā鍨?- 鍙互鍦ㄩ」鐩骇鎴栫敤鎴风骇浣滅敤鍩熷畾涔?- 閫氳繃 `/agents` 鏌ョ湅銆佺鐞嗐€佺敓鎴?
鏉ユ簮锛?
- Anthropic Docs 鈥?Subagents: <https://docs.anthropic.com/en/docs/claude-code/sub-agents>

### 闃舵 2锛歂amed subagent 涓?fork 鏄袱绉嶄笉鍚岃涔?
瀹樻柟鏂囨。鏄庣‘鍖哄垎锛?
- **Named subagents**锛氫笓闂ㄨ鑹层€佺嫭绔嬭亴璐ｃ€乫resh context
- **Task tool forks**锛氬熀浜庡綋鍓嶄笂涓嬫枃缁х画鍒嗘敮锛屽拰 named subagent 涓嶅悓

骞朵笖鏂囨。鏄庣‘缁欏嚭浜?鈥淗ow forks differ from named subagents鈥?鐨勮涔夎竟鐣屻€?
鏉ユ簮锛?
- Anthropic Docs 鈥?Subagents: <https://docs.anthropic.com/en/docs/claude-code/sub-agents>

### 闃舵 3锛氬墠鍙?/ 鍚庡彴鏄繍琛屾椂姒傚康锛屼笉鏄?prompt 鎶€宸?
Claude Code 鏂囨。鏄庣‘鍐欏埌锛?
- subagent 鍙互 **foreground**
- 涔熷彲浠?**background**
- 杩樻彁渚?Agent view / 鍚庡彴浠诲姟鏌ョ湅涓庝腑鏂兘鍔?
鏉ユ簮锛?
- Anthropic Docs 鈥?Subagents: <https://docs.anthropic.com/en/docs/claude-code/sub-agents>
- Anthropic Docs 鈥?Agent view: <https://docs.anthropic.com/en/docs/claude-code/agent-view>

### 闃舵 4锛氬苟鍙戝娲炬槸鎺ㄨ崘宸ヤ綔娴?
Claude Code 鐨勫伐浣滄祦鏂囨。鏄庣‘鎺ㄨ崘锛?
- 瀵圭嫭绔嬬殑浠ｇ爜搴撴悳绱?/ 璋冩煡浠诲姟浣跨敤澶氫釜 subagents 骞惰
- 鐒跺悗鐢辩埗浠ｇ悊缁煎悎缁撴灉

涔熷氨鏄锛屼竴瀵瑰鍐嶇患鍚堬紝涓嶆槸鏃侀棬琛屼负锛岃€屾槸瀹樻柟榧撳姳鐨勬爣鍑嗘ā寮忋€?
鏉ユ簮锛?
- Anthropic Docs 鈥?Common workflows: <https://docs.anthropic.com/en/docs/claude-code/common-workflows>

### 闃舵 5锛氶暱浠诲姟 / 鎸佺画浠诲姟鏈夌嫭绔嬫仮澶嶈涔?
瀹樻柟鏂囨。鎻愬埌锛?
- subagent 鍙悗鍙拌繍琛?- 鍙互鍦?Agent view 涓鐞?- 闀夸换鍔′細鑷姩 compact
- 淇敼 subagent 閰嶇疆鏃讹紝姝ｅ湪杩愯鐨勪細璇濅笉浼氳姹℃煋锛屾柊閰嶇疆鍙奖鍝嶆柊浼氳瘽

杩欒鏄?Claude Code 鐨?child lifecycle 鏄?Runtime-owned锛屼笉鏄?prompt-owned銆?
鏉ユ簮锛?
- Anthropic Docs 鈥?Subagents: <https://docs.anthropic.com/en/docs/claude-code/sub-agents>
- Anthropic Docs 鈥?Agent view: <https://docs.anthropic.com/en/docs/claude-code/agent-view>

---

## 閫愰」瀵规瘮

| 缁村害 | Claude Code | forge-agent 褰撳墠瀹炵幇 | 瀵归綈搴?|
|---|---|---|---|
| **瀛愪唬鐞嗘槸鍘熺敓鑳藉姏** | 鏄紝/agents + runtime-owned lifecycle | 鏄紝SessionRuntime 涓哄敮涓€涓婚摼 | 鉁?|
| **named vs fork 璇箟鍒嗙** | 鏄庣‘鍖哄垎 | 宸?typed 鍒嗙锛歠resh vs parent snapshot | 鉁?|
| **child session 鎸佷箙鍖?* | 鏄?| 鏄紝SessionStore + typed notifications | 鉁?|
| **fan-out 骞跺彂** | 鎺ㄨ崘宸ヤ綔娴?| 宸叉敮鎸?read-only parallel-safe fan-out | 鉁?|
| **foreground / background** | 鍘熺敓杩愯鏃舵蹇?| 宸叉敮鎸侊紝浣嗛粯璁ょ瓥鐣ヤ粛鍋忎繚瀹?| 馃煛 |
| **鍚庡彴缁撴灉鍥炴祦** | Agent view / background lifecycle | append_agent_notification + claim_agent_completions | 鉁?|
| **鐖朵唬鐞嗙患鍚堝洖鍚堟敹鏉?* | 鏄庢樉瀛樺湪 runtime-owned synthesis 鑺傚 | 宸叉湁鏈€灏忕増锛氭敹鍒?child completion 鍚庢挙鎺夋柊鐨?Agent 涓€杞?| 馃煛 |
| **child control surface** | 鏇村儚鐙珛鑳藉姏闈紙鏌ョ湅 / 涓柇 / 缁х画锛?| 鐩墠鑱氬悎鍦?`agent_control` | 馃煛 |
| **live steering running child** | 瀹樻柟鏈?Agent view / interrupt / manage 璇箟 | 褰撳墠浠?terminal resume锛況unning child 涓嶈兘 live steer | 馃煛 |
| **nested delegation 澹版槑璇箟** | 鏂囨。/宸ュ叿闈㈠亸鏄惧紡 | 褰撳墠 primary 鐢?allowlist锛涢潪 primary 渚濊禆 `Agent` tool role锛岃€岄潪 typed allowlist | 馃煛 |
| **subagent 鎶€鑳?/ memory / mcp / hooks 缁勫悎** | 瀹樻柟鏀寔閰嶇疆鍖栫粍鍚?| 鐩墠澶ч儴鍒嗗凡鑳借繘鍏ヤ富閾撅紝浣嗚繕鏈夐浂鏁ｅ樊寮傚緟缁х画瀹¤ | 馃煛 |
| **缁煎悎鍚庢仮澶?delegation 鑺傚** | 鏇村儚鏄惧紡 runtime discipline | 褰撳墠鍙湁鈥滀竴杞挙 Agent鈥濇渶灏忓疄鐜?| 馃煛 |
| **prompt 渚濊禆绋嬪害** | 杩愯鏃跺绾︽洿閲嶏紝prompt 杈呭姪 | 浠嶆湁 `_SUBAGENT_PROTOCOL` 娈嬬暀渚濊禆 | 馃煛 |

---

## 宸窛娓呭崟

### Gap 1锛歠oreground / background 榛樿绛栫暐杩樹笉澶熸帴杩?Claude Code

**CC**

- 鍚庡彴 child 鏄爣鍑嗗伐浣滄柟寮忎箣涓€
- 骞惰璋冪爺銆侀暱浠诲姟銆佺嫭绔嬭皟鏌ュぉ鐒堕€傚悎 background

**鎴戜滑褰撳墠**

- `AgentSpawnRequest.resolve_execution_placement()` 宸叉敮鎸?`AUTO`
- named child 鍙湁 `definition.background=true` 鏃舵墠浼氳嚜鍔ㄨ蛋 background
- fork 榛樿 foreground锛岄櫎闈炴樉寮忚姹?background

**闂**

- 杩欒繕鏄€滃畾涔夐┍鍔ㄩ粯璁ゅ€尖€濓紝涓嶆槸鈥渞untime 鏍规嵁浠诲姟褰㈡€佸拰鐖朵唬鐞嗛渶瑕佸喅瀹氣€濈殑鏇撮珮灞傜瓥鐣?- 瀵逛竴瀵瑰鐙珛璋冩煡鏉ヨ锛岄粯璁ゅ墠鍙颁粛鐒跺亸淇濆畧

**娑夊強浠ｇ爜**

- [agent/session/models.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/models.py:555>)
- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:322>)

**姝ｇ‘鏂瑰悜**

- 淇濈暀 typed `ExecutionPlacement`
- 浣嗘妸 鈥淎UTO 濡備綍鍐崇瓥鈥?浠?definition.background 鍗曠偣锛屽崌绾т负锛?  - definition.background
  - parent intent
  - fan-out cardinality
  - 鏄惁闇€瑕佸綋鍓嶆绔嬪嵆娑堣垂缁撴灉
  鍥涜€呭叡鍚屽喅瀹氱殑 runtime policy


### Gap 4锛歳unning child 浠嶇劧涓嶈兘 live steer

**CC**

- 浠?Agent view 鍏紑琛屼负鏉ョ湅锛岃繍琛屼腑 child 鑷冲皯瀛樺湪鈥滃彲绠＄悊銆佸彲涓柇鈥濈殑寮鸿繍琛屾椂璇箟

**鎴戜滑褰撳墠**

- `send_agent_message()` 鍙厑璁?terminal child resume
- running child 浼氳繑鍥?`RUNNING_UNAVAILABLE`

**闂**

- 杩欐剰鍛崇潃鎴戜滑鐜板湪鏇村儚鈥滃悗鍙颁换鍔?+ 缁撴潫鍚庣户缁€濓紝鑰屼笉鏄€滅湡姝ｅ彲浜や簰 child lifecycle鈥?
**娑夊強浠ｇ爜**

- [agent/session/runtime.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1145>)
- [agent/session/agent_control_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/agent_control_tool.py:152>)

**姝ｇ‘鏂瑰悜**

- 鍒嗕袱姝ュ仛锛屼笉涓€姝ュ埌浣嶏細
  1. 鍏堟妸 running child 鐨?`wait/cancel` 璺緞鍋氬己
  2. 鍐嶅喅瀹氭槸鍚﹀疄鐜扮湡姝ｇ殑 live message channel

### Gap 5锛歯ested delegation 鐨勫０鏄庤涔変粛涓嶅 Claude Code 椋庢牸

**CC 鍊惧悜**

- delegation grant 鏇村亸 declarative銆佹樉寮忋€佸彲瑙?
**鎴戜滑褰撳墠**

- primary agent锛歵yped `DelegationPolicy.allowlist(...)`
- non-primary agent锛氫笉鑳藉０鏄?primary-style allowlist锛涙槸鍚﹀彲鍐嶅娲句富瑕佸彇鍐充簬鏄惁澹版槑 `Agent` tool role

**闂**

- 杩欒鈥渟ubagent 鍐嶆淳 subagent鈥濈殑鎺堟潈璇箟涓嶅缁熶竴
- primary / non-primary 浣跨敤涓ゅ琛ㄨ揪鏂瑰紡

**娑夊強浠ｇ爜**

- [agent/session/models.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/models.py:236>)
- [agent/session/models.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/models.py:514>)
- [agent/session/agent_registry.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/agent_registry.py:151>)

**姝ｇ‘鏂瑰悜**

- 缁熶竴鎴愪竴涓?declarative delegation contract
- 涓嶅啀鍖哄垎鈥減rimary 鎵嶈兘 typed allowlist锛宻ubagent 鍙兘闈?tool role鈥?
### Gap 6锛歚_SUBAGENT_PROTOCOL` 浠嶆湁鍓╀綑 prompt 鑰﹀悎

**CC**

- prompt 浼氳緟鍔╋紝浣嗙湡姝ｇ殑鐢熷懡鍛ㄦ湡 / 鏉冮檺 / tool contract 閮界敱 runtime 鍐冲畾

**鎴戜滑褰撳墠**

- 宸茬粡鍓婅杽杩?`_SUBAGENT_PROTOCOL`
- 浣嗗畠浠嶆壙杞斤細
  - 鍒嗘瀽绾緥
  - 杈撳嚭瑕佹眰
  - 涓€浜涢獙璇佹彁绀?
**闂**

- 鍐嶅線鍚庣户缁紨杩涙椂锛屽緢瀹规槗鎶?runtime discipline 鍙堝鍥?prompt

**娑夊強浠ｇ爜**

- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:48>)
- [agent/session/task_tool.py](</D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:600>)

**姝ｇ‘鏂瑰悜**

- 缁х画鎶婂彲楠岃瘉鐨勮鍒欎笅娌夊埌 runtime / schema / typed result
- prompt 鍙繚鐣欙細
  - fresh vs fork 鎻愰啋
| Gap 6锛堢户缁笅娌?`_SUBAGENT_PROTOCOL`锛?| P2 | 閲嶈锛屼絾瑕佸缓绔嬪湪鍓嶉潰 runtime fact 鏇寸ǔ涔嬪悗 |
| Gap 7锛堟枃妗?canonical 鍖栵級 | P2 | 闃叉缁х画琚棫鎻忚堪甯﹀亸 |

---

## 寤鸿鍒嗘壒鏀归€犺鍒?
### Batch S1锛氬缓绔嬬湡姝ｇ殑 post-child synthesis runtime phase

**鐩爣**

- 鎶婄洰鍓嶁€滀竴杞挙鎺?Agent鈥濈殑鏈€灏忓疄鐜帮紝鍗囩骇鎴愭樉寮忎笖鍙祴璇曠殑 runtime phase discipline

**淇敼鑼冨洿**

- `agent/core.py`
- `agent/session/runtime.py`
- `agent/session/runtime_prompt_builder.py`
- `tests/test_v2_runtime.py`

**瑕佸仛鐨勪簨**

1. 鎶?post-child synthesis turn 鎶芥垚鏄庣‘鐨?runtime fact锛岃€屼笉鏄暎钀藉湪 loop 涓殑灞€閮ㄥ竷灏斿€笺€?2. 鍖哄垎涓ょ child 鍚庣疆鐘舵€侊細
   - 鏀跺埌 completion锛岀瓑寰呯患鍚?   - child 缁撴灉闇€瑕?resolution锛堝 worktree / resume / wait锛?3. 涓烘瘡绉嶇姸鎬佸畾涔夊厑璁稿伐鍏烽泦鍚堛€?4. 琛ョ鍒扮娴嬭瘯锛?   - fan-out 鍚庣珛鍗冲啀寮€鏂?Agent 琚?runtime 鎷︿綇
   - worktree child 鏈?resolve 鏃?finish 琚尅鍥?   - resolve 瀹屾垚鍚?delegation 鍙噸鏂板紑鏀?
**瀹屾垚鏍囧織**

- 涓嶅啀闈犳枃妗ｈ鏈?overlay锛岃€屾槸娴嬭瘯鍙瘉鏄庢湁鐪熷疄 phase discipline

### Batch S2锛氬崌绾?AUTO placement 鍐崇瓥

**鐩爣**

- 璁?`ExecutionPlacement.AUTO` 鏇存帴杩?Claude Code 鐨?runtime 椋庢牸

**淇敼鑼冨洿**

- `agent/session/models.py`
- `agent/session/task_tool.py`
- `agent/session/runtime.py`
- `tests/test_v2_runtime.py`

**瑕佸仛鐨勪簨**

1. 淇濈暀 `ExecutionPlacement` enum 涓嶅彉銆?2. 鏂板 runtime-level placement policy helper锛?   - 鑻ョ埗浠ｇ悊涓€娆″彂鍑哄涓彧璇荤嫭绔嬭皟鏌ヤ换鍔?鈫?榛樿 background
   - 鑻?child 缁撴灉琚綋鍓嶆绔嬪嵆闇€瑕?鈫?foreground
   - fork 浠嶉粯璁ゆ洿淇濆畧锛屼絾鍏佽鎸夊満鏅彁鍗囧埌 background
3. 涓嶅紩鍏ュ瓧绗︿覆 heuristics锛涘彧鍏佽鍩轰簬 typed facts 鍐崇瓥銆?
**瀹屾垚鏍囧織**

- AUTO 涓嶅啀鍙槸 `definition.background` 鐨勫埆鍚?
### Batch S3锛氭媶鍒?child control surface

**鐩爣**

- 鎶?`agent_control` 浠庤仛鍚堝伐鍏锋媶鎴愭竻鏅拌兘鍔涢潰

**淇敼鑼冨洿**

- `agent/session/agent_control_tool.py`
- `agent/session/registry_builder.py`
- `tests/test_v2_runtime.py`
- `docs/v2-react-architecture.md`

**瑕佸仛鐨勪簨**

1. 淇濈暀 runtime API锛?   - `send_agent_message`
   - `wait_for_agent`
   - `cancel_agent`
2. 宸ュ叿灞傛媶鎴愶細
   - `SendMessage`
   - `WaitForAgent`
   - `CancelAgent`
3. `agent_control` 鍏堜繚鐣欏吋瀹瑰眰锛屽啀閫愭閫€鍦恒€?
**瀹屾垚鏍囧織**

- schema 鏇存竻鏅?- prompt 鏇村鏄撹〃杈?- 鍚?Claude Code 椋庢牸鏇撮潬杩?
### Batch S4锛氱粺涓€ nested delegation 鐨勫０鏄庢ā鍨?
**鐩爣**

- primary / non-primary 浣跨敤鍚屼竴濂?declarative delegation contract

**淇敼鑼冨洿**

- `agent/session/models.py`
- `agent/session/agent_registry.py`
- `agent/session/agent_definition.py`
- `tests/test_v2_runtime.py`

**瑕佸仛鐨勪簨**

1. 缁熶竴 `DelegationPolicy` 鍦?primary / subagent 涓婄殑浣跨敤鏂瑰紡銆?2. 绂佹帀鈥滈潬鏄惁澹版槑 Agent tool role 闂存帴鍐冲畾鑳藉惁鍐嶅娲锯€濈殑鍗婇殣寮忚涔夈€?3. 鎵€鏈?delegation grant 閮借蛋鍚屼竴濂?typed allowlist / scope 楠岃瘉銆?
**瀹屾垚鏍囧織**

- nested delegation 璇箟瀹屽叏澹版槑寮?
### Batch S5锛氳瘎浼板苟鍐冲畾鏄惁瀹炵幇 running child live steering

**鐩爣**

- 鍏堣皟鐮旓紝鍐嶅喅瀹氭槸鍚﹀疄鐜扮湡姝ｇ殑 live message channel

**淇敼鑼冨洿**

- 鍏堟枃妗ｄ笌娴嬭瘯鍘熷瀷锛屼笉鍏堣惤鐢熶骇閫昏緫

**瑕佸仛鐨勪簨**

1. 鍖哄垎锛?   - interrupt / cancel
   - terminal resume
   - live steering
2. 鑻ヨ瀹炵幇 live steering锛屽繀椤诲厛瀹氫箟锛?   - mailbox / channel ownership
   - message delivery boundary
   - 浣曟椂褰卞搷褰撳墠 child step
   - 鏄惁闇€瑕?worker thread cooperative polling

**瀹屾垚鏍囧織**

- 鏈夋槑纭?go / no-go 鍐崇瓥锛岃€屼笉鏄洸鏀?
### Batch S6锛氱户缁墛寮?`_SUBAGENT_PROTOCOL`

**鐩爣**

- 鎶婁粛鍦?prompt 涓殑绾緥缁х画涓嬫矇

**淇敼鑼冨洿**

- `agent/session/task_tool.py`
- `agent/session/subagent.py`
- `tests/test_v2_runtime.py`

**瑕佸仛鐨勪簨**

1. 鎶婂彲楠岃瘉杈撳嚭瑕佹眰缁х画杞垚 typed result / validator銆?2. prompt 鍙繚鐣欐渶灏忚鑹茶鏄庯細
   - 浣犳槸 fresh context
   - 鍙仛杩欎釜 scope
   - 鎸夎繖涓?deliverable 杩斿洖

**瀹屾垚鏍囧織**

- `_SUBAGENT_PROTOCOL` 缁х画鍙樼煭
- runtime contract 缁х画鍙樺己

### Batch S7锛氭枃妗?canonical 鍖?
**鐩爣**

- 缁熶竴鍚庣画鎵€鏈?Subagent 璁捐璁ㄨ鐨勪簨瀹炴簮

**淇敼鑼冨洿**

- `docs/subagent-comparison.md`
- `docs/v2-react-architecture.md`
- `docs/session-runtime-v2.md`
- 鍏朵粬鍘嗗彶鏂囨。鐨勨€滃凡杩囨椂璇存槑鈥?
**瑕佸仛鐨勪簨**

1. 鏍囧嚭 canonical doc銆?2. 鏃ф枃妗ｉ噷鍑℃槸涓庡綋鍓嶅疄鐜板啿绐佺殑鍐呭锛岀粺涓€杩藉姞鈥滆繃鏃惰鏄庘€濇垨鏀瑰啓銆?3. 涓嶅啀淇濈暀澶氫釜浜掔浉鍐茬獊鐨?Subagent 鍙欒堪鐗堟湰銆?
---

## Current canonical execution plan

This section supersedes the earlier batch list in this document. Completed
batches S1-S4 are intentionally removed from the active execution view so the
remaining plan is the only source of truth for ongoing work.

### Completed and removed from active plan

- S1: post-child synthesis runtime phase
- S2: AUTO placement runtime policy
- S3: child control surface split
- S4: nested delegation declarative unification

### Remaining execution batches

#### S5a: lock down running-child control boundaries

Scope:

- `agent/session/runtime.py`
- `agent/session/agent_control_tool.py`
- `tests/test_v2_runtime.py`
- `docs/v2-react-architecture.md`

Goals:

1. Make the current contract explicit:
   - running child: `WaitForAgent` / `CancelAgent` only
   - terminal child: `SendMessage` resumes execution
   - live steering: explicitly unsupported today
2. Add tests for split child-control tools and compatibility `agent_control`.
3. Align tool descriptions, errors, and docs so they no longer imply that a
   running child can accept live follow-up messages.

Done when:

- running-child control semantics are defined by tests and docs, not by code reading

#### S5b: produce a go / no-go decision for true live steering

Scope:

- `docs/subagent-comparison.md`
- targeted prototype tests only if needed

Goals:

1. Separate four concepts cleanly:
   - interrupt / cancel
   - wait / observe
   - terminal resume
   - true live steering
2. Only allow implementation work if all preconditions are explicit:
   - mailbox ownership
   - delivery boundary
   - child-step consumption boundary
   - interaction with cancellation / compaction / resume ordering
3. Write a go / no-go decision with reasons.

Done when:

- live steering has an explicit architectural decision, not an implicit drift

##### S5b decision: no-go on the current Subagent runtime track

Decision:

- **No-go for implementing true live steering inside the current Subagent runtime path.**

Reasoning:

1. Claude Code鈥檚 public behavior separates several concepts that we should not
   collapse into one implementation:
   - terminal subagent resume
   - fork steering from an opened transcript/panel
   - teammate-to-teammate direct messaging
2. Claude Code鈥檚 own public docs describe direct inter-agent messaging as part
   of **agent teams**, not ordinary subagent result return. Team communication is
   backed by an explicit mailbox and shared coordination substrate, whereas
   subagents primarily work in their own context and report back to the caller.
3. Our current runtime objectively owns only:
   - child cancellation tokens
   - background thread handles
   - terminal resume with persisted transcript
   It does **not** own:
   - a durable mailbox per running child
   - message ordering across cancel / compact / resume
   - step-boundary delivery semantics for mid-turn message consumption
4. Adding 鈥渓ive steering鈥?directly to `send_agent_message()` would therefore
   create a false Claude-Code likeness: similar surface wording, different
   underlying contract.

Required preconditions before reconsidering a go decision:

1. A Runtime-owned mailbox/channel per running child.
2. Typed delivery semantics for when a child may consume new messages.
3. Ordering guarantees across wait/cancel/resume/compaction.
4. Explicit distinction between:
   - subagent result-return path
   - fork steering path
   - agent-team communication path

Architectural consequence:

- If we later want true running-agent messaging, we should treat it as an
  **agent-team / communication-substrate feature**, not as a small extension of
  the current subagent resume API.

#### S5c: if and only if S5b says go, build the smallest viable live channel

Scope:

- deferred until S5b decision

Goals:

1. If go: implement only cooperative minimal delivery.
2. If no-go: harden the existing model and document the absence of a child-team
   communication channel.

Done when:

- the running-child message model is no longer ambiguous

#### S6a: continue moving enforceable subagent rules out of `_SUBAGENT_PROTOCOL`

Scope:

- `agent/session/task_tool.py`
- `agent/session/subagent.py`
- `tests/test_v2_runtime.py`

Goals:

1. Identify remaining prompt rules that can become runtime facts.
2. Convert more output requirements into typed result or validator enforcement.
3. Leave only irreducible role/context reminders in prompt text.

Done when:

- `_SUBAGENT_PROTOCOL` gets shorter again without losing behavior guarantees

#### S6b: reduce prompt responsibility to fresh/fork/scope/deliverable guidance

Scope:

- `agent/session/task_tool.py`
- `agent/session/runtime_prompt_builder.py`
- `tests/test_v2_runtime.py`

Goals:

1. Remove duplicated discipline language.
2. Avoid restating Runtime-owned facts in prompt text.
3. Ensure parent / child / fork prompt layers no longer conflict.

Done when:

- prompt is guidance only, not protocol truth

#### S7a: canonicalize Subagent docs

Scope:

- `docs/subagent-comparison.md`
- `docs/v2-react-architecture.md`
- `docs/session-runtime-v2.md`

Goals:

1. Mark canonical docs clearly.
2. Rewrite or obsolete statements that conflict with current implementation.
3. Standardize terminology: Agent, named subagent, fork, background, resume, synthesis.

Done when:

- future design discussion is anchored on one current fact source

#### S7b: de-conflict historical docs

Scope:

- historical docs that still describe obsolete subagent behavior

Goals:

1. Find old tool names, old flow diagrams, and stale capability claims.
2. Add obsolescence markers or minimal corrections only where needed.

Done when:

- historical docs no longer contradict the canonical Subagent docs

## 鎬讳綋鍒ゆ柇

鎬讳綋缁撹涓嶆槸鈥滃綋鍓?Subagent 鏋舵瀯璧板亸浜嗏€濓紝鑰屾槸锛?
- **鏍稿績楠ㄦ灦宸茬粡鍩烘湰瀵逛簡**
  - SessionRuntime 涓婚摼
  - typed spawn contract
  - fresh vs fork 鍒嗙
  - background completion durable notification
  - fan-out + synthesis 鍩烘湰鑳藉姏

- **浣嗕笂灞傝繍琛屾椂鑺傚浠嶇劧鍋忊€滃崐鏄惧紡鈥?*
  - synthesis phase 鍙湁鏈€灏忓疄鐜?  - AUTO placement 浠嶅亸淇濆畧
  - child control surface 杩樹笉澶熸竻鏅?  - nested delegation 鐨勫０鏄庤涔夎繕涓嶅缁熶竴

鎵€浠ュ悗缁纭柟鍚戜笉鏄帹缈婚噸鍋氾紝鑰屾槸锛?
1. 缁х画鎶婅繍琛屾椂浜嬪疄琛ラ綈锛?2. 鎶?prompt 璐熸媴缁х画涓嬫矇锛?3. 鎶婂伐鍏烽潰鍜屽０鏄庨潰鍋氬緱鏇存竻妤氾紱
4. 姣忎竴鎵归兘鐢?runtime tests 閽変綇锛屼笉鍐嶄緷璧栤€滄枃妗ｉ噷鍐欎簡杩欎釜妯″紡鈥濄€?
---

## 澶栭儴鍙傝€冩潵婧?
浠ヤ笅鏉ユ簮鐢ㄤ簬鎸囧鏈姣旀枃妗ｇ殑 Claude Code 渚у垽鏂細

1. Anthropic Docs 鈥?Subagents  
   <https://docs.anthropic.com/en/docs/claude-code/sub-agents>

2. Anthropic Docs 鈥?Agent view  
   <https://docs.anthropic.com/en/docs/claude-code/agent-view>

3. Anthropic Docs 鈥?Common workflows  
   <https://docs.anthropic.com/en/docs/claude-code/common-workflows>

> 娉細浠ヤ笂鍏紑璧勬枡瓒充互鏀寔鈥淪ubagents 鏄師鐢熻兘鍔涖€佹敮鎸佸墠鍚庡彴銆佹敮鎸佸苟琛屽娲俱€佸己璋?child lifecycle 鐢?runtime 鎸佹湁鈥濊繖浜涚粨璁恒€傛洿缁嗙矑搴︾殑瀹炵幇缁嗚妭锛堜緥濡傚唴閮ㄦ秷鎭€荤嚎銆佺簿纭仮澶嶇姸鎬佹満鍛藉悕锛夊畼鏂规湭瀹屽叏鍏紑锛屽洜姝ゆ湰鏂囩浉搴旈儴鍒嗗彧缁欏嚭鈥滃簲瀵归綈鐨勮涓鸿竟鐣屸€濓紝涓嶈櫄鏋勫唴閮ㄥ疄鐜般€?
