import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

from database import db, create_document, get_documents
from schemas import GuildConfig, RoleMapping, MemberLink, AssignmentRequest

DISCORD_API_BASE = "https://discord.com/api/v10"

app = FastAPI(title="Discord Role Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------- Utility functions ---------

def _collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db[name]


def get_guild_config(guild_id: str) -> Optional[dict]:
    return _collection("guildconfig").find_one({"guild_id": guild_id})


def get_role_mapping(guild_id: str, plan: str) -> Optional[dict]:
    return _collection("rolemapping").find_one({"guild_id": guild_id, "plan": plan})


def discord_headers(bot_token: str):
    return {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
        "User-Agent": "Flames-Discord-Automation (https://flames.run, 1.0)"
    }


def add_role_to_member(bot_token: str, guild_id: str, user_id: str, role_id: str):
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    r = requests.put(url, headers=discord_headers(bot_token))
    if r.status_code not in (204, 201):
        raise HTTPException(status_code=502, detail=f"Discord add role failed: {r.status_code} {r.text}")


def remove_role_from_member(bot_token: str, guild_id: str, user_id: str, role_id: str):
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    r = requests.delete(url, headers=discord_headers(bot_token))
    if r.status_code not in (204, 200):
        raise HTTPException(status_code=502, detail=f"Discord remove role failed: {r.status_code} {r.text}")


# --------- Models for requests ---------

class GuildConfigIn(GuildConfig):
    pass

class RoleMappingIn(RoleMapping):
    pass

class MemberLinkIn(MemberLink):
    pass

class WebhookEvent(BaseModel):
    provider: str
    type: str
    plan: Optional[str] = None
    provider_user_id: Optional[str] = None
    guild_id: str
    action: Optional[str] = None  # assign | remove


# --------- Basic routes ---------

@app.get("/")
def read_root():
    return {"message": "Discord Role Automation Backend is running"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# --------- Guild configuration ---------

@app.post("/api/guilds/config")
def upsert_guild_config(payload: GuildConfigIn):
    col = _collection("guildconfig")
    existing = col.find_one({"guild_id": payload.guild_id})
    data = payload.model_dump()
    if existing:
        col.update_one({"_id": existing["_id"]}, {"$set": data})
        guild = col.find_one({"_id": existing["_id"]})
    else:
        create_document("guildconfig", data)
        guild = col.find_one({"guild_id": payload.guild_id})
    return {"status": "ok", "guild": {k: v for k, v in guild.items() if k != "bot_token"}}

@app.get("/api/guilds")
def list_guilds():
    guilds = get_documents("guildconfig")
    # Do not leak tokens
    sanitized = []
    for g in guilds:
        g.pop("bot_token", None)
        sanitized.append(g)
    return {"items": sanitized}


# --------- Role mappings ---------

@app.post("/api/mappings")
def create_or_update_mapping(payload: RoleMappingIn):
    col = _collection("rolemapping")
    existing = col.find_one({"guild_id": payload.guild_id, "plan": payload.plan})
    data = payload.model_dump()
    if existing:
        col.update_one({"_id": existing["_id"]}, {"$set": data})
    else:
        create_document("rolemapping", data)
    return {"status": "ok"}

@app.get("/api/mappings")
def list_mappings(guild_id: Optional[str] = None):
    filt = {"guild_id": guild_id} if guild_id else None
    items = get_documents("rolemapping", filt)
    return {"items": items}


# --------- Member links (optional) ---------

@app.post("/api/links")
def upsert_member_link(payload: MemberLinkIn):
    col = _collection("memberlink")
    existing = col.find_one({
        "provider": payload.provider,
        "provider_user_id": payload.provider_user_id,
        "guild_id": payload.guild_id,
    })
    data = payload.model_dump()
    if existing:
        col.update_one({"_id": existing["_id"]}, {"$set": data})
    else:
        create_document("memberlink", data)
    return {"status": "ok"}

@app.get("/api/links")
def list_links(provider: Optional[str] = None, guild_id: Optional[str] = None):
    filt = {}
    if provider:
        filt["provider"] = provider
    if guild_id:
        filt["guild_id"] = guild_id
    items = get_documents("memberlink", filt or None)
    return {"items": items}


# --------- Role assignment ---------

@app.post("/api/assign")
def assign_role(req: AssignmentRequest):
    guild = get_guild_config(req.guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild config not found")
    mapping = get_role_mapping(req.guild_id, req.plan)
    if not mapping:
        raise HTTPException(status_code=404, detail="Plan to role mapping not found")

    add_role_to_member(guild["bot_token"], req.guild_id, req.discord_user_id, mapping["role_id"])
    return {"status": "assigned", "role_id": mapping["role_id"]}


@app.post("/api/remove")
def remove_role(req: AssignmentRequest):
    guild = get_guild_config(req.guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild config not found")
    mapping = get_role_mapping(req.guild_id, req.plan)
    if not mapping:
        raise HTTPException(status_code=404, detail="Plan to role mapping not found")

    remove_role_from_member(guild["bot_token"], req.guild_id, req.discord_user_id, mapping["role_id"])
    return {"status": "removed", "role_id": mapping["role_id"]}


# --------- Generic webhook (MVP) ---------

@app.post("/api/webhooks/provider")
def generic_webhook(event: WebhookEvent):
    """
    Minimal webhook to react to external provider events.
    Provide: provider, type, guild_id, plan, provider_user_id, action
    For MVP we expect MemberLink entries mapping provider_user_id -> discord_user_id.
    """
    if not event.plan:
        raise HTTPException(status_code=400, detail="Missing plan")
    if event.action not in ("assign", "remove", None):
        raise HTTPException(status_code=400, detail="Invalid action")

    # Find link to Discord user
    link = _collection("memberlink").find_one({
        "provider": event.provider,
        "provider_user_id": event.provider_user_id,
        "guild_id": event.guild_id,
    })
    if not link:
        raise HTTPException(status_code=404, detail="Member link not found for provider user")

    action = event.action or ("assign" if event.type.endswith("created") else "remove")

    req = AssignmentRequest(guild_id=event.guild_id, discord_user_id=link["discord_user_id"], plan=event.plan)
    if action == "assign":
        return assign_role(req)
    else:
        return remove_role(req)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
