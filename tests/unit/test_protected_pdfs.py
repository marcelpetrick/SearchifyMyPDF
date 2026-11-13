# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Password-protected and owner-restricted PDFs (ADR 0011) with a fake engine."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import pikepdf
import pytest

from searchify_pdf.application.workflow import (
    MAX_PASSWORD_ATTEMPTS,
    BatchRunner,
    Choice,
    PasswordAnswer,
)
from searchify_pdf.cli.main import TerminalDecisions, main, read_password_file
from searchify_pdf.domain.jobs import Outcome, Reason
from searchify_pdf.domain.settings import Settings, UiLanguage
from searchify_pdf.engines.pdf_inspect import (
    PdfInspectionError,
    Protection,
    count_pages,
    encrypt_like,
    inspect_pdf,
)
from tests import synthetic
from tests.fakes import FakeEngine
from tests.textutil import sha256

GIB = 1024**3


class PasswordPrompts:
    """Answers password prompts from a queue and records (name, retry)."""

    def __init__(self, *answers: PasswordAnswer | None) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, bool]] = []

    def existing_output(self, source: Path, destination: Path) -> None:
        return None

    def existing_text(
        self, source: Path, text_pages: int, total_pages: int, quality: object = None
    ) -> None:
        return None

    def password(self, source: Path, retry: bool) -> PasswordAnswer | None:
        self.asked.append((source.name, retry))
        return self.answers.pop(0) if self.answers else None


def run(
    paths: list[Path],
    settings: Settings | None = None,
    **kw: object,
) -> tuple[BatchRunner, list[Outcome], list[Reason]]:
    runner = BatchRunner(
        settings or Settings(),
        FakeEngine(),
        version="9.9.9",
        resources=lambda: (8, 64 * GIB),
        **kw,  # type: ignore[arg-type]
    )
    summary = runner.run(paths)
    return runner, [r.outcome for r in summary.results], [r.reason for r in summary.results]


def secret(password: str = "secret") -> PasswordAnswer:
    return PasswordAnswer(Choice.YES, password)


# -- inspection ---------------------------------------------------------------------------


def test_inspection_reports_password_required_and_wrong_password(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    with pytest.raises(PdfInspectionError) as missing:
        inspect_pdf(src)
    assert missing.value.reason is Reason.PASSWORD_REQUIRED
    with pytest.raises(PdfInspectionError) as wrong:
        inspect_pdf(src, "nope")
    assert wrong.value.reason is Reason.WRONG_PASSWORD


def test_inspection_with_user_and_owner_password(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    user = inspect_pdf(src, "secret")
    assert user.encrypted and user.page_count == 1 and not user.any_text
    assert user.protection == Protection("secret", False, user.protection.permissions)  # type: ignore[union-attr]
    assert user.protection is not None and not user.protection.restricted_only
    owner = inspect_pdf(src, "owner")
    assert owner.protection is not None and owner.protection.owner
    assert "secret" not in repr(user.protection) and "***" in repr(user.protection)


def test_restricted_pdf_opens_without_password(tmp_path: Path) -> None:
    info = inspect_pdf(synthetic.restricted_pdf(tmp_path / "r.pdf"))
    assert info.protection is not None and info.protection.restricted_only
    assert not info.protection.permissions.extract
    assert info.pages_with_text == (False,)


def test_blank_owner_password_is_not_a_restriction(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "plain.pdf")
    blank = tmp_path / "blank.pdf"
    with pikepdf.open(src) as pdf:
        pdf.save(blank, encryption=pikepdf.Encryption(owner="", user=""))
    info = inspect_pdf(blank)
    assert info.protection is not None and info.protection.owner
    assert not info.protection.restricted_only


def test_encrypt_like_keeps_password_and_restrictions(tmp_path: Path) -> None:
    plain = synthetic.scanned_pdf(tmp_path / "plain.pdf")
    restricted = pikepdf.Permissions(extract=False, modify_other=False)
    user_only = tmp_path / "user.pdf"
    encrypt_like(plain, user_only, Protection("pw", False, restricted))
    with pikepdf.open(user_only, password="pw") as pdf:
        assert pdf.user_password_matched and not pdf.owner_password_matched
        assert not pdf.allow.extract and pdf.encryption.R == 6
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(user_only)
    as_owner = tmp_path / "owner.pdf"
    encrypt_like(plain, as_owner, Protection("pw", True, restricted))
    with pikepdf.open(as_owner, password="pw") as pdf:
        assert pdf.owner_password_matched
    open_but_restricted = tmp_path / "restricted.pdf"
    encrypt_like(plain, open_but_restricted, Protection("", False, restricted))
    assert count_pages(open_but_restricted) == 1
    with pikepdf.open(open_but_restricted) as pdf:
        assert pdf.is_encrypted and not pdf.owner_password_matched and not pdf.allow.extract


# -- workflow -----------------------------------------------------------------------------


def test_password_prompt_produces_a_copy_protected_the_same_way(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "Statement.pdf")
    before = sha256(src)
    prompts = PasswordPrompts(secret())
    _, outcomes, _ = run([src], decisions=prompts)
    assert outcomes == [Outcome.CONVERTED]
    assert prompts.asked == [("Statement.pdf", False)]
    copy = tmp_path / "Statement_searchable.pdf"
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(copy)
    with pikepdf.open(copy, password="secret") as pdf:
        assert "/SearchifyPDF" in pdf.docinfo and len(pdf.pages) == 1
    assert sha256(src) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Statement.pdf",
        "Statement_searchable.pdf",
    ]


def test_decrypted_work_files_are_private_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "tmp"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))
    seen: list[tuple[Path, int]] = []

    def writer(request: object) -> None:
        source = request.source  # type: ignore[attr-defined]
        seen.append((source, os.stat(source.parent).st_mode & 0o777))
        assert not pikepdf.open(source).is_encrypted  # the engine gets a plain copy
        Path(request.output).write_bytes(source.read_bytes())  # type: ignore[attr-defined]

    docs = tmp_path / "docs"
    docs.mkdir()
    src = synthetic.encrypted_pdf(docs / "e.pdf")
    runner = BatchRunner(
        Settings(),
        FakeEngine(writer=writer),
        decisions=PasswordPrompts(secret()),
        resources=lambda: (8, 64 * GIB),
    )
    assert runner.run([src]).results[0].outcome is Outcome.CONVERTED
    assert seen and seen[0][0].parent.parent == work
    assert os.name == "nt" or seen[0][1] == 0o700  # mkdtemp: owner-only on POSIX
    assert list(work.iterdir()) == []
    assert sorted(p.name for p in docs.iterdir()) == ["e.pdf", "e_searchable.pdf"]


def test_wrong_password_is_asked_again_then_fails(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    prompts = PasswordPrompts(*[secret("bad")] * MAX_PASSWORD_ATTEMPTS)
    _, outcomes, reasons = run([src], decisions=prompts)
    assert outcomes == [Outcome.FAILED] and reasons == [Reason.WRONG_PASSWORD]
    assert [retry for _name, retry in prompts.asked] == [False, True, True]
    assert not (tmp_path / "e_searchable.pdf").exists()


def test_empty_password_counts_as_wrong_and_retry_succeeds(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    prompts = PasswordPrompts(secret(""), secret())
    _, outcomes, _ = run([src], decisions=prompts)
    assert outcomes == [Outcome.CONVERTED]
    assert prompts.asked == [("e.pdf", False), ("e.pdf", True)]


def test_entered_password_is_reused_for_the_rest_of_the_batch(tmp_path: Path) -> None:
    a = synthetic.encrypted_pdf(tmp_path / "a.pdf")
    b = synthetic.encrypted_pdf(tmp_path / "b.pdf")
    other = synthetic.encrypted_pdf(tmp_path / "c.pdf", user_password="different")
    prompts = PasswordPrompts(secret(), secret("different"))
    _, outcomes, _ = run([a, b, other], decisions=prompts)
    assert outcomes == [Outcome.CONVERTED] * 3
    assert [name for name, _ in prompts.asked] == ["a.pdf", "c.pdf"]


def test_skip_and_cancel_answers(tmp_path: Path) -> None:
    a = synthetic.encrypted_pdf(tmp_path / "a.pdf")
    b = synthetic.encrypted_pdf(tmp_path / "b.pdf")
    _, outcomes, reasons = run([a, b], decisions=PasswordPrompts(PasswordAnswer(Choice.NO)))
    assert outcomes[0] is Outcome.SKIPPED and reasons[0] is Reason.USER_SKIPPED
    runner, outcomes, _ = run([a, b], decisions=PasswordPrompts(PasswordAnswer(Choice.CANCEL)))
    assert outcomes == [Outcome.CANCELLED, Outcome.CANCELLED] and runner.cancel.is_set()


def test_non_interactive_without_passwords_fails_clearly(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    _, outcomes, reasons = run([src])
    assert outcomes == [Outcome.FAILED] and reasons == [Reason.PASSWORD_REQUIRED]


def test_passwords_given_up_front_are_tried_without_prompting(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    prompts = PasswordPrompts()
    _, outcomes, _ = run([src], decisions=prompts, passwords=["wrong", "", "secret", "secret"])
    assert outcomes == [Outcome.CONVERTED] and prompts.asked == []


def test_owner_password_copy_opens_with_that_password(tmp_path: Path) -> None:
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    _, outcomes, _ = run([src], passwords=["owner"])
    assert outcomes == [Outcome.CONVERTED]
    with pikepdf.open(tmp_path / "e_searchable.pdf", password="owner") as pdf:
        assert pdf.owner_password_matched


def test_restricted_pdfs_need_the_setting_and_keep_restrictions(tmp_path: Path) -> None:
    src = synthetic.restricted_pdf(tmp_path / "r.pdf")
    _, outcomes, reasons = run([src])
    assert outcomes == [Outcome.FAILED] and reasons == [Reason.RESTRICTED]
    assert not (tmp_path / "r_searchable.pdf").exists()
    _, outcomes, _ = run([src], Settings(process_restricted_pdfs=True))
    assert outcomes == [Outcome.CONVERTED]
    with pikepdf.open(tmp_path / "r_searchable.pdf") as pdf:
        assert pdf.is_encrypted and not pdf.owner_password_matched
        assert not pdf.allow.extract and not pdf.allow.modify_other


def test_protected_pdf_with_text_everywhere_is_copied_protected(tmp_path: Path) -> None:
    plain = synthetic.digital_pdf(tmp_path / "plain.pdf")
    src = tmp_path / "d.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(src, encryption=pikepdf.Encryption(owner="o", user="secret"))
    plain.unlink()
    _, outcomes, _ = run([src], passwords=["secret"])
    assert outcomes == [Outcome.PRESERVED]
    with pikepdf.open(tmp_path / "d_searchable.pdf", password="secret") as pdf:
        assert "/SearchifyPDF" in pdf.docinfo


def test_signed_protected_pdf_stays_rejected(tmp_path: Path) -> None:
    signed = synthetic.signed_pdf(tmp_path / "s.pdf")
    src = tmp_path / "sp.pdf"
    with pikepdf.open(signed) as pdf:
        pdf.save(src, encryption=pikepdf.Encryption(owner="o", user="secret"))
    _, outcomes, reasons = run([src], passwords=["secret"])
    assert outcomes == [Outcome.FAILED] and reasons == [Reason.SIGNED]


def test_engine_failure_on_protected_pdf_removes_work_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "tmp"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))
    docs = tmp_path / "docs"
    docs.mkdir()
    src = synthetic.encrypted_pdf(docs / "e.pdf")
    runner = BatchRunner(
        Settings(),
        FakeEngine(fail=Reason.ENGINE_FAILED),
        passwords=["secret"],
        resources=lambda: (8, 64 * GIB),
    )
    assert runner.run([src]).results[0].reason is Reason.ENGINE_FAILED
    assert list(work.iterdir()) == []
    assert [p.name for p in docs.iterdir()] == ["e.pdf"]


# -- CLI ----------------------------------------------------------------------------------


def test_password_file_lines(tmp_path: Path) -> None:
    file = tmp_path / "pw.txt"
    file.write_text("first\n\n with spaces \r\nlast", encoding="utf-8")
    assert read_password_file(file) == ("first", " with spaces ", "last")


def test_terminal_password_prompt_answers() -> None:
    out = io.StringIO()
    answers = TerminalDecisions(UiLanguage.ENGLISH, io.StringIO("pw\n\n"), out)
    assert answers.password(Path("x.pdf"), False) == PasswordAnswer(Choice.YES, "pw")
    assert answers.password(Path("x.pdf"), True) == PasswordAnswer(Choice.NO)
    assert answers.password(Path("x.pdf"), True) == PasswordAnswer(Choice.CANCEL)
    text = out.getvalue()
    assert "“x.pdf” is password-protected" in text and "Wrong password" in text


def test_terminal_password_prompt_hides_input_on_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    calls: list[str] = []

    def fake_getpass(prompt: str, stream: object = None) -> str:
        calls.append(prompt)
        return "hidden"

    monkeypatch.setattr("getpass.getpass", fake_getpass)
    answers = TerminalDecisions(UiLanguage.GERMAN, Tty(), io.StringIO())
    assert answers.password(Path("x.pdf"), False) == PasswordAnswer(Choice.YES, "hidden")
    assert calls and calls[0].startswith("Passwort")


def test_cli_password_file_and_restricted_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(tmp_path))
    docs = tmp_path / "docs"
    docs.mkdir()
    synthetic.encrypted_pdf(docs / "e.pdf")
    synthetic.restricted_pdf(docs / "r.pdf")
    pw = tmp_path / "pw.txt"
    pw.write_text("secret\n", encoding="utf-8")
    out = io.StringIO()
    code = main(
        ["--cli", "--password-file", str(pw), "--process-restricted", str(docs)],
        stdin=io.StringIO(),
        stdout=out,
        engine_factory=FakeEngine,
    )
    assert code == 0, out.getvalue()
    assert (docs / "e_searchable.pdf").exists() and (docs / "r_searchable.pdf").exists()
    assert "secret" not in out.getvalue()


def test_cli_unreadable_password_file_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(tmp_path))
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    code = main(
        ["--cli", "--password-file", str(tmp_path / "missing.txt"), str(src)],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        engine_factory=FakeEngine,
    )
    assert code == 2


def test_cli_non_interactive_protected_pdf_reports_password_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(tmp_path))
    src = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    out = io.StringIO()
    code = main(
        ["--cli", "--non-interactive", str(src)],
        stdin=io.StringIO(),
        stdout=out,
        engine_factory=FakeEngine,
    )
    assert code == 1 and "--password-file" in out.getvalue()


def test_pikepdf_access_is_serialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """qpdf's crypto is not thread-safe on Windows: every open happens under one lock."""
    from searchify_pdf.engines import pdf_inspect, pdf_ops

    opened: list[bool] = []
    real_open = pikepdf.open

    def checked_open(*args: object, **kwargs: object) -> pikepdf.Pdf:
        opened.append(pdf_ops._PIKEPDF_LOCK.locked())
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pdf_inspect, "backend", pdf_inspect.InProcess)  # observe the opens
    monkeypatch.setattr(pdf_ops.pikepdf, "open", checked_open)
    a = synthetic.encrypted_pdf(tmp_path / "a.pdf")
    r = synthetic.restricted_pdf(tmp_path / "r.pdf")
    opened.clear()  # only the application's opens count, not the fixtures'
    _, outcomes, _ = run(
        [a, r], Settings(process_restricted_pdfs=True), decisions=PasswordPrompts(secret())
    )
    assert outcomes == [Outcome.CONVERTED] * 2
    assert opened and all(opened)
    assert not pdf_ops._PIKEPDF_LOCK.locked()
