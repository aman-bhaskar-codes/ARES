import builtins
from types import SimpleNamespace

import pytest

from ares.application.exports import ExportError, ExportService
from ares.domain.models import RunMode, RunStatus


def test_missing_pdf_renderer_rejects_export_instead_of_returning_html(monkeypatch):
    real_import = builtins.__import__

    def import_without_playwright(name, *args, **kwargs):
        if name == 'playwright.sync_api':
            raise ImportError('renderer unavailable')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_playwright)
    run = SimpleNamespace(id='run', query='Question', mode=RunMode.QUICK,
                          status=RunStatus.COMPLETED, answer_blocks=[], gaps=[])
    with pytest.raises(ExportError, match='PDF renderer'):
        ExportService(None, None)._pdf(run, [])
