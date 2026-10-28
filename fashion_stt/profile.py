"""Opt-in single-user profile storage and privacy-scoped recommendation context.

This is not an authentication system. Do not enable it on a shared server.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, select, delete
from sqlalchemy.schema import CreateTable
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from trend_system.database.session import _build_async_engine
from trend_system.config import BASE_DIR

def get_profile_engine():
    # A separate SQLite file prevents personal data being written into the
    # repository's tracked historical trends.db. Uses the same engine factory.
    url = os.getenv("PROFILE_DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'profiles.db'}")
    return _build_async_engine(url)

logger = logging.getLogger(__name__)
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ListValues = Annotated[list[Short], Field(max_length=30)]

class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Personal(Group):
    display_name: Short | None = None
    age_range: Short | None = None
    gender_presentation: Short | None = None
    country: Short | None = None
    city: Short | None = None
    preferred_language: Short | None = None
    units: Literal['metric', 'imperial'] | None = None

class Style(Group):
    preferred_styles: ListValues = Field(default_factory=list)
    preferred_colors: ListValues = Field(default_factory=list)
    avoided_colors: ListValues = Field(default_factory=list)
    preferred_patterns: ListValues = Field(default_factory=list)
    style_inspiration: Note | None = None
    fashion_goals: ListValues = Field(default_factory=list)
    trend_interest: Literal['low', 'medium', 'high'] | None = None
    style_experimentation: Literal['conservative', 'balanced', 'experimental'] | None = None

class Sizes(Group):
    fit_preference: Literal['slim', 'regular', 'relaxed', 'oversized'] | None = None
    top_size: Short | None = None
    bottom_size: Short | None = None
    dress_size: Short | None = None
    shoe_size: Short | None = None
    shoe_size_system: Literal['EU', 'US', 'UK'] | None = None
    size_notes: Note | None = None

class Shopping(Group):
    budget_level: Literal['budget-conscious', 'moderate', 'premium', 'luxury'] | None = None
    preferred_brands: ListValues = Field(default_factory=list)
    avoided_brands: ListValues = Field(default_factory=list)
    shopping_priorities: ListValues = Field(default_factory=list)

class Lifestyle(Group):
    common_occasions: ListValues = Field(default_factory=list)
    lifestyle_notes: Note | None = None
    climate_comfort: Literal['hot', 'mild', 'cold'] | None = None
    comfort_priorities: ListValues = Field(default_factory=list)

class Restrictions(Group):
    avoided_materials: ListValues = Field(default_factory=list)
    clothing_restrictions: ListValues = Field(default_factory=list)
    coverage_preference: Short | None = None
    accessibility_preferences: ListValues = Field(default_factory=list)
    additional_notes: Note | None = None

class ProfileData(Group):
    personal: Personal = Field(default_factory=Personal)
    style: Style = Field(default_factory=Style)
    sizes: Sizes = Field(default_factory=Sizes)
    shopping: Shopping = Field(default_factory=Shopping)
    lifestyle: Lifestyle = Field(default_factory=Lifestyle)
    restrictions: Restrictions = Field(default_factory=Restrictions)

# The same group schemas support nested PATCH: exclude_unset distinguishes omitted
# fields from explicit nulls. Validation of the merged result catches null lists.
class ProfilePatch(Group):
    personal: Personal | None = None
    style: Style | None = None
    sizes: Sizes | None = None
    shopping: Shopping | None = None
    lifestyle: Lifestyle | None = None
    restrictions: Restrictions | None = None

    @model_validator(mode='after')
    def groups_not_null(self):
        for key in self.model_fields_set:
            if getattr(self, key) is None:
                raise ValueError(f'{key} must be an object')
        return self

class ProfileResponse(ProfileData):
    id: str
    created_at: str
    updated_at: str

class ProfileContext(Group):
    available: bool
    status: Literal['ok', 'no_profile', 'unavailable', 'disabled']
    # Only populated values are included; database identity and private notes never leave storage.
    preferences: dict = Field(default_factory=dict)

metadata = MetaData()
profiles = Table('user_profiles', metadata,
    Column('owner', String(64), primary_key=True),
    Column('id', String(36), nullable=False, unique=True),
    Column('data', JSON, nullable=False),
    Column('created_at', String(40), nullable=False),
    Column('updated_at', String(40), nullable=False),
)
OWNER = 'local-single-user'

def enabled() -> bool:
    return os.getenv('PROFILE_LOCAL_MODE', '').lower() in ('1', 'true')

def same_origin(request: Request) -> bool:
    origin = request.headers.get('origin')
    if not origin:
        return True  # non-browser clients; local mode is not authentication
    parsed = urlsplit(origin)
    return parsed.scheme in ('http', 'https') and parsed.netloc.lower() == request.headers.get('host', '').lower()

def require_local(request: Request):
    if not enabled():
        raise HTTPException(503, 'Profile is disabled. PROFILE_LOCAL_MODE=1 enables single-user development mode only.')
    if not same_origin(request):
        raise HTTPException(403, 'Cross-origin profile access is not permitted.')

async def initialize():
    async with get_profile_engine().begin() as conn:
        await conn.execute(CreateTable(profiles, if_not_exists=True))

async def load_profile():
    await initialize()
    async with get_profile_engine().connect() as conn:
        row = (await conn.execute(select(profiles).where(profiles.c.owner == OWNER))).mappings().first()
        return dict(row) if row else None

def response(row):
    return ProfileResponse(**row['data'], id=row['id'], created_at=row['created_at'], updated_at=row['updated_at'])

async def save_profile(payload, partial=False):
    await initialize()
    engine = get_profile_engine()
    async with engine.connect() as conn:
        # Serialize read/modify/write on SQLite; PostgreSQL row locks for existing rows.
        if engine.dialect.name == 'sqlite':
            await conn.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            await conn.begin()
        try:
            query = select(profiles).where(profiles.c.owner == OWNER)
            if engine.dialect.name != 'sqlite':
                # Advisory transaction lock serializes creation too (PostgreSQL).
                from sqlalchemy import text
                await conn.execute(text('SELECT pg_advisory_xact_lock(719321558)'))
                query = query.with_for_update()
            row = (await conn.execute(query)).mappings().first()
            if partial and not row:
                raise HTTPException(404, 'Profile not found')
            if partial:
                data = dict(row['data'])
                for group, changes in payload.model_dump(exclude_unset=True).items():
                    data[group] = {**data[group], **changes}
                data = ProfileData.model_validate(data).model_dump()
            else:
                data = payload.model_dump()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                await conn.execute(profiles.update().where(profiles.c.owner == OWNER).values(data=data, updated_at=now))
                result = {**dict(row), 'data': data, 'updated_at': now}
            else:
                result = dict(owner=OWNER, id=str(uuid.uuid4()), data=data, created_at=now, updated_at=now)
                await conn.execute(profiles.insert().values(**result))
            await conn.commit()
            return response(result)
        except BaseException:
            await conn.rollback()
            raise

async def safely(operation):
    try:
        return await operation
    except (SQLAlchemyError, ValidationError):
        # SQLAlchemy and validation exception strings can contain private values.
        logger.error('Profile storage operation failed (details withheld for privacy)')
        raise HTTPException(503, 'Profile storage is unavailable') from None

router = APIRouter(prefix='/api/v1/profile', tags=['Profile'])

@router.get('', response_model=ProfileResponse)
async def get_profile(request: Request):
    require_local(request)
    row = await safely(load_profile())
    if not row:
        raise HTTPException(404, 'Profile not found')
    try:
        return response(row)
    except ValidationError:
        raise HTTPException(503, "Stored profile is unavailable") from None

@router.put('', response_model=ProfileResponse)
async def put_profile(payload: ProfileData, request: Request):
    require_local(request)
    return await safely(save_profile(payload))

@router.patch('', response_model=ProfileResponse)
async def patch_profile(payload: ProfilePatch, request: Request):
    require_local(request)
    return await safely(save_profile(payload, partial=True))

@router.delete('', status_code=204)
async def delete_profile(request: Request):
    require_local(request)
    async def remove():
        await initialize()
        async with get_profile_engine().begin() as conn:
            result = await conn.execute(delete(profiles).where(profiles.c.owner == OWNER))
            if not result.rowcount:
                raise HTTPException(404, 'Profile not found')
    await safely(remove())
    return Response(status_code=204)

async def context_for_request(request: Request, structured) -> ProfileContext:
    if not enabled() or not same_origin(request):
        return ProfileContext(available=False, status='disabled')
    try:
        row = await load_profile()
        if not row:
            return ProfileContext(available=False, status='no_profile')
        data = ProfileData.model_validate(row['data'])
        # Conservative allowlist. No personal details or private free-text notes.
        # General inquiries receive only style/color; outfit tasks include practical
        # restrictions. Sizes only for explicit relevant garment requests.
        general = structured.intent.type == 'general_inquiry'
        keys = {'style': ['preferred_styles', 'preferred_colors', 'avoided_colors']}
        if not general:
            keys.update({
                'style': ['preferred_styles', 'preferred_colors', 'avoided_colors', 'preferred_patterns', 'fashion_goals', 'trend_interest', 'style_experimentation'],
                'sizes': ['fit_preference'],
                'shopping': ['budget_level', 'preferred_brands', 'avoided_brands', 'shopping_priorities'],
                'lifestyle': ['common_occasions', 'climate_comfort', 'comfort_priorities'],
                'restrictions': ['avoided_materials', 'clothing_restrictions', 'coverage_preference', 'accessibility_preferences'],
            })
            # Explicit shoe requests only, not inferred location or unrelated queries.
            import re
            text = structured.clean_input or ''
            if re.search(r'\b(shoes?|boots?|sneakers?|footwear|sandals?|heels?)\b', text, re.I):
                keys['sizes'] += ['shoe_size', 'shoe_size_system']
        preferences = {}
        for group, names in keys.items():
            for name in names:
                value = getattr(getattr(data, group), name)
                if value is not None and value != []:
                    preferences[name] = value
        return ProfileContext(available=True, status='ok', preferences=preferences)
    except Exception:
        logger.error('Profile context retrieval failed (details withheld for privacy)')
        return ProfileContext(available=False, status='unavailable')
