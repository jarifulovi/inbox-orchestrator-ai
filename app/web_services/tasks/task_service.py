# app/web_services/tasks/task_service.py
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client
from app.core.schemas.tasks import (
    VALID_TASK_STATUSES,
    VALID_TASK_SOURCES,
    VALID_TASK_PRIORITIES,
    VALID_INTENT_LABELS,
)
from app.web_services.tasks.thread_workflow_synchronizer import ThreadWorkflowSynchronizer


class TaskWebService:
    """
    Dedicated web service for Task operations:
    task listing, filtering, creation, partial updates, deletion, and analytics.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client or get_supabase_client()
        self.synchronizer = ThreadWorkflowSynchronizer(self.db)

    async def get_user_tasks(
            self,
            user_id: str,
            account_id: Optional[str] = None,
            priority: Optional[str] = None,
            status: Optional[str] = None,
            intent_label: Optional[str] = None,
            overdue: Optional[bool] = None,
            source: Optional[str] = None,
            email_id: Optional[str] = None,
            limit: int = 20,
            offset: int = 0
    ) -> Dict[str, Any]:
        """
        Fetches tasks with comprehensive filtering and resolves thread subject context.
        """
        try:
            query = self.db.table("tasks").select("*", count="exact").eq("user_id", user_id)

            if account_id:
                query = query.eq("connected_account_id", account_id)

            if email_id:
                query = query.eq("email_id", email_id)

            if priority and priority.strip() and priority.lower() != "all":
                p_val = priority.strip().lower()
                query = query.in_("priority", [p_val, p_val.capitalize(), p_val.upper()])

            if status and status.strip() and status.lower() != "all":
                query = query.eq("status", status.strip().lower())

            if intent_label and intent_label.strip() and intent_label.lower() != "all":
                query = query.eq("intent_label", intent_label.strip().lower())

            if source and source.strip() and source.lower() != "all":
                src = source.strip().lower()
                if src == "system":
                    query = query.or_("source.eq.system,source.is.null")
                else:
                    query = query.eq("source", src)

            if overdue:
                now_iso = datetime.now(timezone.utc).isoformat()
                query = query.eq("status", "pending").lt("due_date", now_iso)

            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
            tasks_res = query.execute()
            tasks_data = tasks_res.data or []
            total_count = tasks_res.count or len(tasks_data)

            if not tasks_data:
                return {"tasks": [], "total_count": 0}

            thread_ids = list({t["thread_id"] for t in tasks_data if t.get("thread_id")})
            threads_map = {}
            if thread_ids:
                try:
                    thr_res = self.db.table("email_threads").select("id, subject").in_("id", thread_ids).execute()
                    threads_map = {t["id"]: (t.get("subject") or "(No Subject)") for t in (thr_res.data or [])}
                except Exception as e:
                    print(f"[TASKS WARNING] Failed to query thread subjects: {e}")

            formatted_tasks = []
            for t in tasks_data:
                t_id = t.get("thread_id")
                formatted_tasks.append({
                    "id": t["id"],
                    "source": t.get("source") or "system",
                    "email_fact_id": t.get("email_fact_id"),
                    "title": t["title"],
                    "priority": (t.get("priority") or "medium").lower(),
                    "status": t["status"],
                    "intent_label": t.get("intent_label") or "other",
                    "due_date": t.get("due_date"),
                    "source_thread_id": t_id,
                    "source_thread_subject": threads_map.get(t_id, "(No Subject)"),
                    "created_at": t.get("created_at")
                })

            return {
                "tasks": formatted_tasks,
                "total_count": total_count
            }
        except Exception as e:
            print(f"[TASKS ERROR] Failed to fetch tasks: {e}")
            return {"tasks": [], "total_count": 0}

    async def get_task_analytics(
            self,
            user_id: str,
            account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculates task analytics metrics for dashboard summary cards.
        """
        try:
            query = self.db.table("tasks").select("id, status, due_date").eq("user_id", user_id)
            if account_id:
                query = query.eq("connected_account_id", account_id)

            res = query.execute()
            all_tasks = res.data or []

            now = datetime.now(timezone.utc)
            pending_count = 0
            completed_count = 0
            overdue_count = 0

            for t in all_tasks:
                st = t.get("status")
                if st == "pending":
                    pending_count += 1
                    due_str = t.get("due_date")
                    if due_str:
                        try:
                            due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                            if due_dt < now:
                                overdue_count += 1
                        except Exception:
                            pass
                elif st == "completed":
                    completed_count += 1

            return {
                "total_tasks": len(all_tasks),
                "pending_tasks": pending_count,
                "completed_tasks": completed_count,
                "overdue_tasks": overdue_count
            }
        except Exception as e:
            print(f"[ANALYTICS ERROR] Failed to compute task analytics: {e}")
            return {
                "total_tasks": 0,
                "pending_tasks": 0,
                "completed_tasks": 0,
                "overdue_tasks": 0
            }

    async def create_manual_task(
            self,
            user_id: str,
            account_id: Optional[str],
            title: str,
            email_id: str,
            thread_id: Optional[str] = None,
            priority: str = "medium",
            intent_label: str = "other",
            due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a new manual task linked to a target email and thread.
        """
        # 1. Verify target email access and retrieve thread_id if needed
        email_res = self.db.table("emails").select("id, thread_id, connected_account_id").eq("id", email_id).execute()
        email_data = email_res.data or []
        if not email_data:
            raise KeyError(f"Target email {email_id} not found.")

        target_email = email_data[0]
        email_account_id = target_email.get("connected_account_id")

        if account_id and email_account_id != account_id:
            raise PermissionError("Access denied to target email account.")

        resolved_account_id = account_id or email_account_id
        if not resolved_account_id:
            raise ValueError("Could not resolve connected_account_id for task.")

        # Verify that resolved_account_id belongs to user_id
        acc_res = self.db.table("connected_accounts").select("id").eq("id", resolved_account_id).eq("user_id", user_id).execute()
        if not acc_res.data:
            raise PermissionError("Access denied: Connected account does not belong to user.")

        resolved_thread_id = thread_id or target_email.get("thread_id")
        if not resolved_thread_id:
            raise ValueError("Could not resolve thread_id from target email.")

        # 2. Build task record payload
        fingerprint = f"manual_{user_id}_{uuid.uuid4().hex}"
        now_iso = datetime.now(timezone.utc).isoformat()

        task_payload = {
            "source": "manual",
            "email_fact_id": None,
            "email_id": email_id,
            "thread_id": resolved_thread_id,
            "user_id": user_id,
            "connected_account_id": resolved_account_id,
            "title": title.strip(),
            "status": "pending",
            "priority": (priority or "medium").strip().lower(),
            "intent_label": (intent_label or "other").strip().lower(),
            "action_fingerprint": fingerprint,
            "due_date": due_date,
            "created_at": now_iso,
            "updated_at": now_iso
        }

        # 3. Insert record into database
        insert_res = self.db.table("tasks").insert(task_payload).execute()
        new_task = (insert_res.data or [task_payload])[0]

        # 4. Auto-sync associated thread workflow_status (raises Exception on failure to ensure atomic operation)
        await self.synchronizer.sync_thread_status(resolved_thread_id, resolved_account_id)

        # 5. Resolve source_thread_subject for response
        thread_subject = "(No Subject)"
        try:
            thr_res = self.db.table("email_threads").select("subject").eq("id", resolved_thread_id).execute()
            if thr_res.data:
                thread_subject = thr_res.data[0].get("subject") or "(No Subject)"
        except Exception:
            pass

        return {
            "id": new_task.get("id", ""),
            "source": "manual",
            "email_fact_id": None,
            "title": new_task["title"],
            "priority": new_task["priority"],
            "status": new_task["status"],
            "intent_label": new_task["intent_label"],
            "due_date": new_task.get("due_date"),
            "source_thread_id": resolved_thread_id,
            "source_thread_subject": thread_subject,
            "created_at": new_task.get("created_at", now_iso)
        }

    async def update_user_task(
            self,
            task_id: str,
            user_id: str,
            title: Optional[str] = None,
            status: Optional[str] = None,
            priority: Optional[str] = None,
            intent_label: Optional[str] = None,
            due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Updates an existing task record (title, status, priority, intent_label, due_date)
        and synchronizes parent thread workflow_status based on remaining tasks and email SLA.
        """
        existing_res = self.db.table("tasks").select("*").eq("id", task_id).execute()
        existing_data = existing_res.data or []
        if not existing_data:
            raise KeyError(f"Task {task_id} not found.")

        task = existing_data[0]
        if task.get("user_id") != user_id:
            raise PermissionError("Access denied to target task.")

        updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if title is not None and title.strip():
            updates["title"] = title.strip()
        if status is not None and status.strip():
            st_val = status.strip().lower()
            if st_val in VALID_TASK_STATUSES:
                updates["status"] = st_val
        if priority is not None and priority.strip():
            p_val = priority.strip().lower()
            if p_val in VALID_TASK_PRIORITIES:
                updates["priority"] = p_val
        if intent_label is not None and intent_label.strip():
            i_val = intent_label.strip().lower()
            if i_val in VALID_INTENT_LABELS:
                updates["intent_label"] = i_val
        if due_date is not None:
            updates["due_date"] = due_date

        upd_res = self.db.table("tasks").update(updates).eq("id", task_id).execute()
        updated_task = (upd_res.data or [task])[0]

        # Sync thread workflow status - raises Exception on failure to ensure task update integrity
        thread_id = updated_task.get("thread_id")
        account_id = updated_task.get("connected_account_id")
        if thread_id:
            await self.synchronizer.sync_thread_status(thread_id, account_id)

        # Resolve thread subject
        thread_subject = "(No Subject)"
        if thread_id:
            try:
                thr_res = self.db.table("email_threads").select("subject").eq("id", thread_id).execute()
                if thr_res.data:
                    thread_subject = thr_res.data[0].get("subject") or "(No Subject)"
            except Exception:
                pass

        return {
            "id": updated_task["id"],
            "source": updated_task.get("source") or "system",
            "email_fact_id": updated_task.get("email_fact_id"),
            "title": updated_task["title"],
            "priority": (updated_task.get("priority") or "medium").lower(),
            "status": updated_task["status"],
            "intent_label": updated_task.get("intent_label") or "other",
            "due_date": updated_task.get("due_date"),
            "source_thread_id": thread_id,
            "source_thread_subject": thread_subject,
            "created_at": updated_task.get("created_at")
        }

    async def delete_user_task(self, task_id: str, user_id: str) -> bool:
        """
        Deletes a task record and updates parent thread workflow status if no pending tasks remain.
        """
        existing_res = self.db.table("tasks").select("id, user_id, thread_id, connected_account_id, status").eq("id", task_id).execute()
        existing_data = existing_res.data or []
        if not existing_data:
            raise KeyError(f"Task {task_id} not found.")

        task = existing_data[0]
        if task.get("user_id") != user_id:
            raise PermissionError("Access denied to target task.")

        thread_id = task.get("thread_id")
        account_id = task.get("connected_account_id")
        self.db.table("tasks").delete().eq("id", task_id).execute()

        if thread_id:
            await self.synchronizer.sync_thread_status(thread_id, account_id)

        return True
