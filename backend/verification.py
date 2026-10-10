"""Identity verification: uploads and the officer queue. Contract 9, docs/PERMITS_AND_VERIFICATION.md.

"Verified" means an officer checked the documents on a date. It is not proof of ownership.
Files live in MongoDB GridFS (MongoDB mode) or in data/uploads (local mode).
"""
import io
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import config
import runtime
from security import current_user, require

router = APIRouter()
ALLOWED = {"image/jpeg", "image/png", "application/pdf"}


def _store_bytes(file_id, data):
    if config.USE_MONGO:
        import gridfs
        from db import get_db
        gridfs.GridFS(get_db()).put(data, _id=file_id)
    else:
        d = config.DATA_DIR / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{file_id}.bin").write_bytes(data)


def _read_bytes(file_id):
    if config.USE_MONGO:
        import gridfs
        from db import get_db
        return gridfs.GridFS(get_db()).get(file_id).read()
    return (config.DATA_DIR / "uploads" / f"{file_id}.bin").read_bytes()


@router.post("/uploads")
async def upload(file: UploadFile, user=Depends(current_user)):
    if file.content_type not in ALLOWED:
        raise HTTPException(415, "Upload a JPG, PNG or PDF")
    data = await file.read(config.UPLOAD_MAX_BYTES + 1)
    if len(data) > config.UPLOAD_MAX_BYTES:
        raise HTTPException(413, "File is larger than 5 MB")
    file_id = runtime.new_id("FILE")
    _store_bytes(file_id, data)
    runtime.insert("files", {"file_id": file_id, "owner_id": user["user_id"], "name": (file.filename or "file")[:80],
                             "content_type": file.content_type, "size": len(data), "created_at": runtime.now_iso()})
    return {"file_id": file_id, "name": file.filename, "size": len(data)}


@router.get("/uploads/{file_id}")
def download(file_id: str, user=Depends(current_user)):
    meta = next((f for f in runtime.all_("files") if f["file_id"] == file_id), None)
    if meta is None:
        raise HTTPException(404, "file not found")
    if user["role"] != "official" and meta["owner_id"] != user["user_id"]:
        raise HTTPException(403, "not your file")
    return Response(_read_bytes(file_id), media_type=meta["content_type"], headers={"Content-Disposition": f'inline; filename="{meta["name"]}"'})


class PilotVerification(BaseModel):
    cert_no: str = Field(min_length=3, max_length=40)
    file_ids: List[str] = Field(min_length=1, max_length=4)


class DroneVerification(BaseModel):
    serial: str = Field(min_length=3, max_length=40)
    uin: Optional[str] = Field(default=None, max_length=40)
    file_ids: List[str] = Field(min_length=1, max_length=4)


def _own_files(user, file_ids):
    owned = {f["file_id"] for f in runtime.all_("files") if f["owner_id"] == user["user_id"]}
    if not set(file_ids) <= owned:
        raise HTTPException(422, "attach files you uploaded")


def _norm(s):
    return "".join(s.split()).upper()


@router.post("/me/verification/pilot")
def verify_pilot(body: PilotVerification, user=Depends(require("pilot"))):
    _own_files(user, body.file_ids)
    cert = _norm(body.cert_no)
    for u in runtime.all_("users"):
        if u["user_id"] != user["user_id"] and _norm(u.get("pilot_cert") or "") == cert and (u.get("verification") or {}).get("status") in ("pending", "verified"):
            raise HTTPException(409, "this certificate number is already registered to another pilot")
    runtime.update("users", "user_id", user["user_id"], {"pilot_cert": body.cert_no.strip(), "verification": {"status": "pending"}})
    return runtime.insert("verifications", {"verification_id": runtime.new_id("V"), "kind": "pilot", "user_id": user["user_id"],
                                            "user_name": user["name"], "data": {"cert_no": body.cert_no.strip()}, "file_ids": body.file_ids,
                                            "status": "pending", "created_at": runtime.now_iso()})


@router.post("/me/drones/{drone_id}/verification")
def verify_drone(drone_id: str, body: DroneVerification, user=Depends(require("pilot"))):
    drone = next((d for d in runtime.all_("drones") if d["drone_id"] == drone_id and d.get("owner_id") == user["user_id"]), None)
    if drone is None:
        raise HTTPException(404, "drone not found on your account")
    _own_files(user, body.file_ids)
    serial = _norm(body.serial)
    for d in runtime.all_("drones"):
        if d["drone_id"] != drone_id and _norm(d.get("serial") or "") == serial and (d.get("verification") or {}).get("status") in ("pending", "verified"):
            raise HTTPException(409, "this serial number is already registered to another drone")
    runtime.update("drones", "drone_id", drone_id, {"serial": body.serial.strip(), "uin": body.uin or drone.get("uin"), "verification": {"status": "pending"}})
    return runtime.insert("verifications", {"verification_id": runtime.new_id("V"), "kind": "drone", "user_id": user["user_id"],
                                            "user_name": user["name"], "drone_id": drone_id, "drone_name": drone["name"],
                                            "data": {"serial": body.serial.strip(), "uin": body.uin}, "file_ids": body.file_ids,
                                            "status": "pending", "created_at": runtime.now_iso()})


@router.get("/verification/queue")
def queue(status: str = "pending", user=Depends(require("official"))):
    items = [v for v in runtime.all_("verifications") if status == "all" or v["status"] == status]
    return sorted(items, key=lambda v: v["created_at"])


class VDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=300)


@router.post("/verification/{verification_id}/decision")
def decide(verification_id: str, body: VDecision, user=Depends(require("official"))):
    v = next((v for v in runtime.all_("verifications") if v["verification_id"] == verification_id), None)
    if v is None:
        raise HTTPException(404, "verification not found")
    if v["status"] != "pending":
        raise HTTPException(409, "already decided")
    if body.decision == "rejected" and not body.comment.strip():
        raise HTTPException(422, "give a reason when rejecting")
    status = "verified" if body.decision == "approved" else "rejected"
    stamp = {"status": status, "by": user["name"], "at": runtime.now_iso(), "comment": body.comment.strip()}
    from bridge import notify
    what = "pilot certificate" if v["kind"] == "pilot" else f"drone {v.get('drone_name')}"
    with runtime.atomic():  # the badge, the review record, the alert and the audit entry change together
        if v["kind"] == "pilot":
            runtime.update("users", "user_id", v["user_id"], {"verification": stamp})
        else:
            runtime.update("drones", "drone_id", v["drone_id"], {"verification": stamp})
        notify(v["user_id"], "verification", f"Verification {body.decision}", f"{user['name']} {body.decision} your {what}. {body.comment.strip()}",
               severity="info" if body.decision == "approved" else "high")
        runtime.audit(user, f"verification_{body.decision}", verification_id, f"{what}. {body.comment.strip()}")
        return runtime.update("verifications", "verification_id", verification_id,
                              {"status": body.decision, "decided_by": user["name"], "decided_at": runtime.now_iso(), "comment": body.comment.strip()})
