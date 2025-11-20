"""
Database Schemas for Discord Role Automation

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- GuildConfig -> "guildconfig"
- RoleMapping -> "rolemapping"
- MemberLink -> "memberlink"
"""

from pydantic import BaseModel, Field
from typing import Optional

class GuildConfig(BaseModel):
    """
    Stores per-guild configuration, including the bot token used to manage roles.
    Collection name: guildconfig
    """
    guild_id: str = Field(..., description="Discord Guild (Server) ID")
    bot_token: str = Field(..., description="Discord Bot Token with Manage Roles permission in the guild")
    guild_name: Optional[str] = Field(None, description="Readable guild name")

class RoleMapping(BaseModel):
    """
    Maps a product/membership plan to a Discord role id within a guild.
    Collection name: rolemapping
    """
    guild_id: str = Field(..., description="Discord Guild ID")
    plan: str = Field(..., description="Product or membership plan identifier")
    role_id: str = Field(..., description="Discord Role ID to assign")
    role_name: Optional[str] = Field(None, description="Readable role name")

class MemberLink(BaseModel):
    """
    Optional linkage of an external user to a Discord user id.
    Collection name: memberlink
    """
    provider: str = Field(..., description="Provider name e.g., stripe, gumroad, patreon")
    provider_user_id: str = Field(..., description="User id at the provider")
    discord_user_id: str = Field(..., description="Discord user id (snowflake)")
    guild_id: str = Field(..., description="Discord Guild ID")

class AssignmentRequest(BaseModel):
    guild_id: str
    discord_user_id: str
    plan: str
