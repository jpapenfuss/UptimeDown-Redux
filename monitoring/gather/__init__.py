"""Gatherer modules for each platform and subsystem.

Platform modules are imported by __main__.py at import time based on sys.platform,
so only the relevant set is ever loaded. Shared utilities live in util.py.
"""
import time
