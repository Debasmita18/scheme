"""
MGNREGA Verification System - Reports Module
=============================================

Provides investigation report generation in multiple formats
including HTML, CAG audit format, and weekly briefings.

Classes:
    ReportGenerator: Generate district reports, case files, and weekly briefings.
"""

from reports.report_generator import ReportGenerator

__all__ = [
    "ReportGenerator",
]
