# -*- coding: utf-8 -*-
"""把执行 YAML 中的桶批次与资源计划幂等写入数据库 v2。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign  # noqa: E402
import naming  # noqa: E402
import workspace_repo  # noqa: E402


def _slot(index, count):
    return "single" if count == 1 else (
        "control" if index == 0 else
        "experiment1" if index == 1 else
        "experiment2"
    )


def _weights(count):
    if count == 1:
        return [100]
    if count == 2:
        return [50, 50]
    if count == 3:
        return [34, 33, 33]
    return [100 // count] * count


def sync_config_batch(v2_db_path, cfg, audiences, started_on,
                      change_reason="", status="planned", created_by="ai"):
    """登记若干桶的同一执行计划；按完整工单名和槽位幂等更新。"""
    conn = workspace_repo.connect(v2_db_path)
    campaign = cfg["campaign"]
    try:
        with workspace_repo.transaction(conn):
            activity_data = {
                "activity_key": campaign["taskGroupName"],
                "display_name": cfg.get("label") or campaign["taskGroupName"],
                "brand": campaign["brand"],
                "owner": campaign["owner"],
                "name_prefix": campaign["namePrefix"],
                "task_group_name": campaign["taskGroupName"],
                "activity_link": campaign["activityLink"],
                "status": campaign.get("status", "active"),
                "started_on": started_on,
                "ended_on": campaign.get("endedAt"),
            }
            existing = workspace_repo.get_activity(conn, campaign["taskGroupName"])
            if existing:
                # 生命周期由数据库启停命令管理；后续执行 YAML 不得把已收尾活动改回 active。
                activity_data.update({
                    "started_on": existing["started_on"],
                    "status": existing["status"],
                    "ended_on": existing["ended_on"],
                })
            activity = workspace_repo.save_activity(conn, activity_data)
            buckets = {}
            for aud in cfg.get("audiences") or []:
                key = str(aud["id"])
                existing = workspace_repo.get_bucket(conn, activity["id"], key)
                threshold = (
                    aud.get("reviewThresholdExposure") or
                    (existing["default_threshold_exposure"] if existing else None) or
                    3000
                )
                buckets[key] = workspace_repo.save_bucket(conn, activity["id"], {
                    "bucket_key": key,
                    "display_name": naming.bucket_name(campaign, aud),
                    "topic": aud.get("topic") or "",
                    "target": aud.get("target") or "",
                    "keywords_text": (aud.get("keywordGroup") or {}).get("keywords") or "",
                    "default_threshold_exposure": int(threshold),
                    "status": "active",
                })
            top_groups = (cfg.get("taskOrder") or {}).get("abGroups") or []
            batch_ids = []
            for aud in audiences:
                key = str(aud["id"])
                task_name = naming.order_task_name(campaign, aud)
                batch = workspace_repo.ensure_batch_for_task(
                    conn, activity["id"], key, task_name, started_on,
                    change_reason=change_reason, created_by=created_by, status=status,
                )
                batch_ids.append(batch["id"])
                groups = aud.get("abGroups") or top_groups or []
                weights = _weights(len(groups))
                copy_by_name = {str(r.get("name")): r for r in (aud.get("resources") or [])}
                for index, group in enumerate(groups):
                    resource_name = str(group.get("resource") or "").strip()
                    if not resource_name:
                        continue
                    copy = (
                        copy_by_name.get(resource_name) or
                        workspace_repo.latest_creative_copy(
                            conn, activity["id"], resource_name) or
                        {}
                    )
                    workspace_repo.save_creative(
                        conn, batch["id"], None, resource_name,
                        copy_id=resource_name,
                        title=copy.get("title") or "",
                        summary=copy.get("summary") or "",
                        angle_key="", style_key="",
                        slot=_slot(index, len(groups)),
                        weight_pct=int(group.get("weightPct") or weights[index]),
                        status="planned" if status == "planned" else "running",
                    )
            return {"activity_id": activity["id"], "batch_ids": batch_ids}
    finally:
        conn.close()
