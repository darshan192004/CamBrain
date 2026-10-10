"""Persistence layer: models, session management, repositories.

Access is confined to this package so a future fleet console can swap in
PostgreSQL without touching the streaming or API layers (spec §6.1).
"""
