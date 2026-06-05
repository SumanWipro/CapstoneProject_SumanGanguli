"""
utils/__init__.py
=================
Shared utility package for the Loan Approval System.

Exports get_logger and write_audit_record as the two primary utilities
consumed by all other packages.
"""

from utils.logger import get_logger
from utils.audit import write_audit_record

__all__ = ["get_logger", "write_audit_record"]
