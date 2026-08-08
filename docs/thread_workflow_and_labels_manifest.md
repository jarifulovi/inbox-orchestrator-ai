# Thread Workflow Statuses & Task Labels Manifest

This manifest formalizes the taxonomy, state transitions, evaluation rules, and code-level documentation basis for **Thread Workflow Statuses**, **Task Statuses**, **Task Sources**, **Intent Labels**, and **Priorities** across the `InboxOrchestratorAI` backend and `inbox-orchestrator-frontend`.

---

## 1. Thread Workflow Status Taxonomy (`workflow_status`)

Stored in `public.email_threads.workflow_status`. Defines the high-level operational lifecycle state of an email conversation thread.

| Status | Label String | Color Theme | Derivation Basis & Evaluation Rules |
| :--- | :--- | :--- | :--- |
| `needs_action` | **Needs Action** | Red (`bg-red-500/10 text-red-400`) | Assigned whenever a thread has at least **1 active pending task** (`status == 'pending'`). This includes **open questions** asked by senders that require the user to answer or provide information. Overrides all other states. |
| `awaiting_reply` | **Awaiting Reply** | Amber (`bg-amber-500/10 text-amber-400`) | Assigned when a thread has **0 pending tasks** for the user, but the user sent the latest email containing a question or request that explicitly expects a reply from the recipient. |
| `follow_up` | **Follow Up** | Purple (`bg-purple-400/10 text-purple-400`) | Assigned when a thread contains a past commitment, open question, or delegated item that requires a future check-in or progress verification (see Section 1.1 below for detailed triggers). |
| `informational` | **Info** | Blue (`bg-blue-400/10 text-blue-400`) | **Default state**. Assigned when a thread has **0 pending tasks** and requires no user action or reply (e.g., newsletters, receipts, automated notifications, or threads where all tasks have been completed/dismissed). |
| `archived` | **Archived** | Zinc (`bg-zinc-500/10 text-zinc-400`) | Assigned when a thread is explicitly archived or removed. **Archived threads are ignored for future background processing and status re-evaluations altogether.** |

### 1.1 Detailed Evaluation Rules for `follow_up`
A thread or task transitions to **`follow_up`** under the following specific operational conditions:
1. **Unanswered Sent Questions**: The user sent an email asking a question or requesting a deliverable, and no response was received within the expected timeframe (e.g., > 48h).
2. **Delegated Action Tracking**: The user assigned or asked a team member/third-party to perform a task and needs to verify completion at a later check-in date.
3. **Deferred Review**: A task has a relative due date set for a future date (e.g., "in 5 days"), placing it into a passive tracking state rather than an immediate `needs_action`.
4. **Explicit User Designation**: The user manually updates a thread's workflow status or task intent to `follow_up`.

### 1.2 Questions as Tasks & Reply Expectations
In `InboxOrchestratorAI`, `ELIGIBLE_TASK_FACT_TYPES = ["task", "commitment", "question"]`. Questions extracted from email bodies are explicitly treated as task items:
- **Questions Asked to User**: Generated as `pending` tasks (`intent_label = "reply_requested"` or `"provide_information"`), driving thread status to `needs_action`.
- **Questions Asked by User**: Tracked as outbound expectations. If unanswered, they transition thread status to `awaiting_reply` (or `follow_up` if overdue).

### 1.3 Tasks Table vs. Email Facts Table Evaluation Matrix

| Status Evaluation | Evaluated From `tasks` Table | Evaluated From `email_facts` Table / Thread Messages | Reason & Technical Mechanics |
| :--- | :---: | :---: | :--- |
| **`needs_action`** | **YES** | No | Checked directly via `tasks.status == 'pending'` (user-assigned tasks/questions). If any pending task exists, thread is immediately `needs_action`. |
| **`awaiting_reply`** | No | **YES** | Outbound questions/requests sent by the user do NOT create tasks for the user in `tasks`. Instead, the AI worker checks `email_facts` on the user's sent emails to see if a reply is expected. |
| **`follow_up`** | **YES** (for user tasks) | **YES** (for outbound facts) | Tasks with `intent_label = 'follow_up'` or deferred due dates are checked from `tasks`. Overdue outbound questions/commitments without a response are checked from `email_facts`. |
| **`informational`** | **YES** | **YES** | Evaluated when `tasks` has 0 pending items AND `email_facts` / thread history shows no expected replies or follow-ups. |

### 1.4 Outbound Email Lifecycle: `awaiting_reply` vs. `follow_up` Disambiguation

To eliminate any ambiguity or conflict when the user sends an outbound email asking a question, the thread transitions through a deterministic, time-bound lifecycle:

```
[User Sends Email with Question]
            │
            ▼
┌──────────────────────────────────────┐
│  Phase 1: Passive Waiting (0h - 48h) │  ──►  workflow_status = "awaiting_reply"
│  • Recipient's turn to answer        │       (Amber badge: "Awaiting Reply")
│  • Within standard SLA window        │
└──────────────────────────────────────┘
            │
            │  (48 hours pass without recipient reply OR deadline reached)
            ▼
┌──────────────────────────────────────┐
│  Phase 2: Overdue / Re-engagement    │  ──►  workflow_status = "follow_up"
│  • Recipient failed to reply in time │       (Purple badge: "Follow Up")
│  • Signals user to nudge or check-in │
└──────────────────────────────────────┘
            │
            │  (User creates explicit nudge task or re-opens thread)
            ▼
┌──────────────────────────────────────┐
│  Phase 3: Active User Nudge Action   │  ──►  workflow_status = "needs_action"
│  • User's turn to send follow-up     │       (Red badge: "Needs Action")
└──────────────────────────────────────┘
```

#### Disambiguation Rules Matrix

| Criteria | `awaiting_reply` | `follow_up` |
| :--- | :--- | :--- |
| **Whose Turn Is It?** | **Recipient's Turn** (User is passively waiting for initial answer). | **User's Turn** to check-in or nudge recipient after no response. |
| **Time Threshold** | **Within SLA Window** (e.g., sent < 48 hours ago). | **SLA Breached** (sent > 48 hours ago without reply) OR scheduled check-in date. |
| **User Action Required?** | **No action yet.** User waits for recipient. | **Action recommended.** Nudge recipient or verify status. |
| **Badge & Visual Indicator** | Amber (`bg-amber-500/10 text-amber-400`) | Purple (`bg-purple-400/10 text-purple-400`) |

### Dynamic Synchronization Rules
1. **Task Creation / Reopening**: When a task's status transitions to `pending`, the associated thread's `workflow_status` is automatically updated to `needs_action`.
2. **Task Completion / Dismissal**: When all tasks belonging to a thread transition to `completed` or `dismissed` (0 pending tasks remain), the thread's `workflow_status` transitions from `needs_action` to `informational` (or `awaiting_reply` / `follow_up` if an outbound reply or check-in is expected from `email_facts`).

---

## 2. Task Lifecycle Status Taxonomy (`status`)

Stored in `public.tasks.status`. Represents the execution state of an individual task item.

| Status | Label String | Derivation & Allowed Actions |
| :--- | :--- | :--- |
| `pending` | **Pending** | Active task requiring resolution (includes unanswered questions requiring user action). Default status upon task creation. |
| `completed` | **Completed** | Task or question answered/resolved by the user or system. Can be reopened to `pending`. |
| `dismissed` | **Dismissed** | Task closed or ignored by the user without completion. Can be reopened to `pending`. |

---

## 3. Task Origin Taxonomy (`source`)

Stored in `public.tasks.source`. Distinguishes how a task was generated.

| Source | Label String | Badge Style | Basis & Description |
| :--- | :--- | :--- | :--- |
| `system` | **System** | Purple Sparkles (`text-purple-400`) | Extracted automatically from email action facts (`task`, `commitment`, `question`) by Gemini LLM in `thread_orchestrator.py`. |
| `manual` | **Manual** | Blue User (`text-blue-400`) | Created explicitly by the user in the frontend linked to a specific target email and thread. |

---

## 4. Task Intent Classification Taxonomy (`intent_label`)

Stored in `public.tasks.intent_label`. Categorizes the semantic intent of the requested action.

| Intent Label | Display String | Semantic Definition & Trigger Examples |
| :--- | :--- | :--- |
| `schedule_meeting` | **Schedule Meeting** | Calendar invites, call requests, meeting coordination, availability inquiries. |
| `reply_requested` | **Reply Requested** | Direct questions asked by sender, feedback requests, explicit calls for a response. |
| `review_document` | **Review Document** | Document reviews, pull requests, file approvals, contract inspect requests. |
| `provide_information` | **Provide Info** | Questions requesting specific data, status updates, context sharing, or details. |
| `make_payment` | **Make Payment** | Invoices, billing statements, subscription renewals, financial transactions. |
| `follow_up` | **Follow Up** | Checking progress on delegated tasks, tracking unanswered outbound questions, scheduled check-ins. |
| `other` | **Other** | **Default category**. General or unclassified task actions. |

---

## 5. Urgency & Priority Taxonomy (`priority`)

Stored in `public.tasks.priority` and `public.email_threads.priority`. Normalized to lowercase strings across database and API layers.

| Priority | Value String | Badge Style | Basis |
| :--- | :--- | :--- | :--- |
| `high` | `"high"` | Red (`badge-high`) | Urgent, time-critical, severe impact (deadlines within 24h, system outages, payment due). |
| `medium` | `"medium"` | Amber/Blue (`badge-medium`) | **Default urgency**. Standard task or thread action. |
| `low` | `"low"` | Zinc/Green (`badge-low`) | Non-urgent, low impact, flexible timeframe. |

---

## 6. Code Base Documentation Plan

We will directly document these definitions into the codebase in the following locations:

1. **[email_threads.py](file:///home/ovi/Desktop/Lab_8th_semester/SPL-03/InboxOrchestratorAI/app/core/schemas/email_threads.py)**: Add docstring and valid constants for `VALID_WORKFLOW_STATUSES` and `VALID_PRIORITIES`.
2. **[tasks.py](file:///home/ovi/Desktop/Lab_8th_semester/SPL-03/InboxOrchestratorAI/app/core/schemas/tasks.py)**: Add docstring and valid constants for `VALID_TASK_STATUSES`, `VALID_TASK_SOURCES`, and `VALID_INTENT_LABELS`.
3. **[thread_orchestrator.py](file:///home/ovi/Desktop/Lab_8th_semester/SPL-03/InboxOrchestratorAI/app/core/workers/thread_orchestrator.py)**: Document the exact status derivation logic in worker docstrings.
4. **[email_web_service.py](file:///home/ovi/Desktop/Lab_8th_semester/SPL-03/InboxOrchestratorAI/app/web_services/email_web_service.py)**: Document thread workflow status auto-sync upon task state update/creation/deletion.
