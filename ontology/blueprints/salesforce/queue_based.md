---
platform: salesforce
platform_display_name: "Salesforce Service Cloud"
routing_model: queue_based
channels: [voice, chat, messaging, email, case]
version: "1.0"
last_verified: 2026-08-09
platform_version_verified_against: "Spring '26"
authored_by: "Swapnil Zade"
produces_events:
  - interaction.received
  - interaction.routed
  - interaction.accepted
  - interaction.declined
  - interaction.expired
  - interaction.talk.start
  - interaction.talk.end
  - interaction.acw.start
  - interaction.acw.end
  - interaction.transferred
  - interaction.abandoned
  - interaction.completed
  - agent.login
  - agent.logout
  - agent.presence.change
tags: [omni-channel, service-cloud]
---

# Overview

Salesforce Omni-Channel with **queue-based routing**: interactions (Cases, Chat sessions, Voice calls, Messaging sessions) land in one of N Queues; agents whose Presence Configuration matches the Queue's Routing Configuration are eligible to receive routed work in a pull-style model.

**When to use this configuration:**
- You want a shared inbox model where agents pull from a queue.
- Routing decisions are primarily "which queue", not "which agent has skill X".
- You have a small-to-medium number of routing distinctions (< ~20 queues per org is comfortable).

**When to use something else:**
- Need attribute-based matching (language, tier, product) → use the `skill_based` blueprint instead.
- Need per-agent capacity overlays and real-time availability → layer the `presence_aware` blueprint on top.
- Need fallback / spillover behavior when a queue can't handle → layer the `overflow_escalation` blueprint on top.

# Prerequisites

- [ ] Salesforce Service Cloud license (Enterprise, Performance, Unlimited, or Developer)
- [ ] Omni-Channel enabled — Setup → Feature Settings → Service → Omni-Channel Settings → check "Enable Omni-Channel"
- [ ] Admin permissions: "Customize Application", "Manage Users", "Manage Public Groups"
- [ ] For voice: Service Cloud Voice add-on license + a configured Contact Center
- [ ] For messaging: Digital Engagement license + at least one Messaging Channel enabled
- [ ] For chat: Live Agent / Embedded Service configured (deprecated but common)

# Configuration steps

1. **Enable Omni-Channel.** Setup → Feature Settings → Service → Omni-Channel Settings → check "Enable Omni-Channel" → Save.
2. **Create Service Channels.** Setup → Feature Settings → Service → Omni-Channel → Service Channels → New. Create one per interaction type you route (e.g., "Case Channel" with Salesforce Object = Case; "Voice Channel" with Salesforce Object = VoiceCall; "Messaging Channel" with Salesforce Object = MessagingSession).
3. **Create Presence Configurations.** Setup → Feature Settings → Service → Omni-Channel → Presence Configurations → New. Define agent capacity per channel (e.g., "up to 5 cases + 1 voice call") and auto-accept behavior.
4. **Create Presence Statuses.** Setup → Feature Settings → Service → Omni-Channel → Presence Statuses → New. At minimum: one "Available" status (StatusOption = Online) linked to your Presence Config's Service Channels; one "Away" and one "Offline" (StatusOption = Away).
5. **Create Queues.** Setup → Users → Queues → New. For each queue:
   - Label + Queue Name
   - Supported Objects: match the Service Channel's SObject (Case, MessagingSession, VoiceCall, etc.)
   - Queue Members: add Users or Public Groups (nested groups are allowed but see Known traps)
6. **Create Omni-Channel Routing Configuration.** Setup → Feature Settings → Service → Omni-Channel → Routing Configurations → New. Set:
   - Routing Model: `Least Active` (assigns to the agent with fewest active items) or `Most Available` (uses spare capacity first)
   - Push Time-Out: seconds before auto-reroute if agent doesn't accept (typical: 30–60s)
7. **Bind Routing Configuration to each Queue.** From the Queue detail page → Routing Configuration lookup → select the Routing Configuration from step 6.
8. **Assign Presence Configuration to agent Users.** User record → Presence Configuration lookup → select the Presence Configuration. Save.
9. **Verify Omni-Channel widget appears** for the agent (utility bar item). If not: check the User's profile has Omni-Channel enabled and the app has the utility bar item configured.

# Object footprint

| Concept | Platform object.field | Populated when | Notes |
|---|---|---|---|
| routing_entity | Group (Type='Queue').Name | Admin creates a Queue | Queues are `Group` records with `Type='Queue'` |
| routing_entity_member | GroupMember.UserOrGroupId | Admin adds a member | Direct User or nested Public Group |
| interaction_record | AgentWork | Interaction is routed | One AgentWork per assignment attempt |
| interaction_open | AgentWork.AcceptDateTime | Agent accepts | Null until acceptance |
| interaction_close | AgentWork.EndDateTime | Agent closes work | ACW may follow via CloseDateTime |
| interaction_declined | AgentWork.DeclineDateTime | Agent declines | AgentWork stays; new attempt spawned |
| pending_routing | PendingServiceRouting | Interaction awaits routing | Deleted once routed — see Known traps |
| agent_presence | UserServicePresence | Agent presence changes | One row per state transition |
| presence_state_type | ServicePresenceStatus | Admin defines a status | StatusOption enum: Online/Away/Offline |
| assignment_rule | OmniChannelRoutingConfig | Admin creates routing config | ModelType='LeastActive' or 'MostAvailable' |

# ACD event mapping

### interaction.received
- **Recorded in:** `PendingServiceRouting` (row is created)
- **Trigger:** A routable object (Case, MessagingSession, VoiceCall, Chat_Transcript) is submitted to a Queue that has an Omni-Channel Routing Configuration bound.
- **Prerequisite events:** none
- **Caveats:** PSR rows are transient — deleted once routed. See Known traps.

### interaction.routed
- **Recorded in:** `AgentWork` (row created; UserId set)
- **Trigger:** OmniChannelRoutingConfig assigns the PSR to an agent per the routing model (Least Active / Most Available).
- **Prerequisite events:** interaction.received
- **Caveats:** For pull-model queues, "routed" is when the agent's queue view refreshes and the item becomes visible in Omni-Channel.

### interaction.accepted
- **Recorded in:** `AgentWork.AcceptDateTime`
- **Trigger:** Agent clicks Accept on the Omni-Channel widget.
- **Prerequisite events:** interaction.routed
- **Caveats:** For voice interactions, AcceptDateTime is the Omni-Channel accept — not when the voice line actually connects. See Known traps.

### interaction.declined
- **Recorded in:** `AgentWork.DeclineDateTime` (and Status = 'Declined')
- **Trigger:** Agent clicks Decline within the Push Time-Out window.
- **Prerequisite events:** interaction.routed
- **Caveats:** Declined AgentWork records persist; a NEW AgentWork is created for the reroute attempt.

### interaction.expired
- **Recorded in:** `AgentWork.Status = 'Timeout'` (and DeclineDateTime is null)
- **Trigger:** Push Time-Out on the Routing Configuration elapses without agent action.
- **Prerequisite events:** interaction.routed
- **Caveats:** Configure Push Time-Out to a value larger than typical agent reaction time or you'll see spurious timeouts.

### interaction.talk.start
- **Recorded in:** For voice: `VoiceCall.CallStartDateTime`. For chat/messaging: `AgentWork.AcceptDateTime` (used as proxy). For Case: not directly modeled (Case has no talk/hold concept).
- **Trigger:** Voice line connects OR chat/messaging session begins.
- **Prerequisite events:** interaction.accepted
- **Caveats:** Voice channel introduces its own timing which can lag AgentWork acceptance by 1–3 seconds. See Known traps.

### interaction.talk.end
- **Recorded in:** For voice: `VoiceCall.CallEndDateTime`. For chat/messaging: `AgentWork.EndDateTime`.
- **Trigger:** Line disconnects / chat session ends.
- **Prerequisite events:** interaction.talk.start
- **Caveats:** ACW immediately follows talk.end — the CloseDateTime is later.

### interaction.acw.start
- **Recorded in:** Implicit — the window between `AgentWork.EndDateTime` and `AgentWork.CloseDateTime` (if the Presence Configuration includes ACW).
- **Trigger:** Talk ends and Presence Configuration says the agent goes into a Wrap-Up state.
- **Prerequisite events:** interaction.talk.end
- **Caveats:** If the Presence Configuration doesn't have a wrap-up state configured, ACW is zero-length.

### interaction.acw.end
- **Recorded in:** `AgentWork.CloseDateTime`
- **Trigger:** Agent clicks Close on the Omni-Channel widget after wrap-up.
- **Prerequisite events:** interaction.acw.start
- **Caveats:** Auto-close after N seconds is configurable; without auto-close, agents can leave records open indefinitely.

### interaction.transferred
- **Recorded in:** New `AgentWork` record on the receiving side; original AgentWork.Status = 'Transferred' or similar.
- **Trigger:** Agent uses "Transfer to Queue" or "Transfer to Agent" in the Omni-Channel widget.
- **Prerequisite events:** interaction.accepted
- **Caveats:** Warm transfer creates a `interaction.consulted` first; cold does not. Salesforce doesn't distinguish warm/cold/blind cleanly at the AgentWork level; check `TransferReason` and correlate.

### interaction.abandoned
- **Recorded in:** `PendingServiceRouting.Status = 'Abandoned'` before it's deleted; captured in AgentWork if the customer disconnects post-routing but pre-accept.
- **Trigger:** Customer disconnects / closes chat before an agent accepts.
- **Prerequisite events:** interaction.received
- **Caveats:** PSR deletion timing makes this brittle to observe — see Known traps.

### interaction.completed
- **Recorded in:** `AgentWork.Status = 'Closed'` + `CloseDateTime` populated
- **Trigger:** All wrap-up complete; agent has closed the work item.
- **Prerequisite events:** interaction.acw.end
- **Caveats:** Auto-close may fire the Closed status without the agent explicitly clicking Close.

### agent.login
- **Recorded in:** `UserServicePresence` (new row created with a StatusId whose StatusOption is not Offline)
- **Trigger:** Agent sets a non-Offline presence status via the Omni-Channel widget.
- **Prerequisite events:** none
- **Caveats:** Presence isn't the same as Salesforce user login — a user can be logged into Salesforce but Offline in Omni-Channel. Discovery must use UserServicePresence, not User.LastLoginDate.

### agent.logout
- **Recorded in:** `UserServicePresence` (new row with an Offline-category StatusId, or the previous row's EndDate)
- **Trigger:** Agent sets Offline presence, closes the browser, or session ends.
- **Prerequisite events:** agent.login
- **Caveats:** Browser close doesn't always emit a clean logout; UserServicePresence may show an open "Online" row indefinitely. Discovery should treat any UserServicePresence older than 24h with no EndDate as effectively logged out.

### agent.presence.change
- **Recorded in:** `UserServicePresence` (new row per transition)
- **Trigger:** Agent selects a different Presence Status in the Omni-Channel widget.
- **Prerequisite events:** agent.login
- **Caveats:** Auto-away transitions (from a Presence Configuration's inactivity timer) show up as system-initiated changes. Attribute mapping: `from_state` = previous row's StatusId → ServicePresenceStatus.StatusOption; `to_state` = current row's.

# Validation

1. **Setup verification.** In Setup, confirm Omni-Channel Settings shows enabled; at least one Service Channel, Presence Config, Presence Status, Queue, and Routing Config exist.
2. **Agent-side verification.** Log in as a User with the Presence Configuration assigned. Confirm the Omni-Channel widget appears in the utility bar. Set presence to Available. The widget should show your accepted-status and 0 active work items.
3. **End-to-end test.**
   - Have a second user (admin) create a Case and set its Owner to the Queue you configured.
   - Within ~2 seconds, expect an `AgentWork` record where UserId = your test agent's ID. SOQL: `SELECT Id, UserId, Status, AcceptDateTime FROM AgentWork ORDER BY CreatedDate DESC LIMIT 1`.
   - Click Accept in the Omni-Channel widget. Re-query — expect `AcceptDateTime` populated.
   - Click Close (or wait for auto-close). Re-query — expect `EndDateTime` and `CloseDateTime` populated.
4. **Presence verification.** SOQL: `SELECT Id, UserId, ServicePresenceStatusId, ConfiguredStatusId, StatusStartDate, StatusEndDate FROM UserServicePresence WHERE UserId = <agent Id> ORDER BY StatusStartDate DESC LIMIT 5`. Expect a row per presence change during the test.

# Known traps

- **AgentWork.AcceptDateTime ≠ voice line-connect time.** Voice channel records its own connect time in `VoiceCall.CallStartDateTime`. Use that if you need accurate talk-time for voice; using AcceptDateTime gives you Omni-Channel acceptance time which precedes actual talk by 1–3 seconds.
- **PendingServiceRouting rows are deleted after routing.** PSR is a working row Omni-Channel uses to track "not-yet-routed". Once routed, it's deleted. To capture `interaction.received` reliably, either (a) enable Field History Tracking on PSR, (b) run discovery frequently against PSR (which risks missing events), or (c) reconstruct from AgentWork.CreatedDate (which is `interaction.routed`, not received — off by the routing latency).
- **Omni-Channel doesn't record hold as a first-class concept.** Hold events live inside the underlying channel: `VoiceCall` transcript events or `Chat_Transcript` events. If hold time matters, layer the voice- or chat-specific blueprint on top of this one. That's why `interaction.hold.*` events are NOT in this blueprint's produces_events.
- **Queue members can be nested Public Groups.** GroupMember.UserOrGroupId can point at a Public Group which itself has GroupMembers. Walking the tree requires recursive expansion; naïve queries miss half the eligible agents.
- **Presence auto-away timers cause spurious declines.** The Presence Configuration has an idle timeout — if an agent doesn't accept within N seconds, they auto-set to Away and their AgentWork.DeclineDateTime is populated as if they'd declined. Configure the timeout explicitly to a value higher than realistic agent reaction time (60+ seconds typical) or accept that DeclineDateTime is a noisy signal.
- **UserServicePresence "still open" rows.** When an agent closes their browser without clicking Offline, the row's EndDate stays null indefinitely. Treat any presence row older than 24 hours with no EndDate as effectively closed.
