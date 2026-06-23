"""v00.99.92 — PR_SET_PDEATHSIG preexec_fn contract.

`_run_subprocess_with_group_kill` spawns antechamber/sqm with
`start_new_session=True`, which isolates them from the parent's
process group so `os.killpg()` on timeout can reap the subtree.

Side-effect of that isolation: when the parent (uvicorn worker /
batch runner) dies ungracefully (SIGKILL, OOM, `uvicorn --reload`),
the child never gets SIGHUP and reparents to init — permanent CPU
leak until the operator notices and kills it manually.

`PR_SET_PDEATHSIG=SIGKILL` asks the Linux kernel to SIGKILL the
child the moment its parent thread exits, regardless of the session
boundary. Applied via `preexec_fn` so the flag is set between
``fork()`` and ``execve()`` in the child process.

These tests lock the contract:
* `_run_subprocess_with_group_kill` passes ``preexec_fn`` to
  ``subprocess.Popen`` and that value is exactly `_pdeathsig_preexec`.
* `_pdeathsig_preexec` on Linux invokes ``libc.prctl`` with
  ``PR_SET_PDEATHSIG=1`` and ``SIGKILL``.
* `_pdeathsig_preexec` on non-Linux (or if prctl raises) silently
  no-ops instead of crashing the child.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.molecules import artifact_service  # noqa: E402


def test_run_subprocess_passes_pdeathsig_preexec_to_popen():
    """Popen must receive the pdeathsig preexec_fn. Locking this
    prevents a future refactor from silently dropping the
    orphan-prevention mechanism."""

    fake_proc = MagicMock()
    fake_proc.communicate.return_value = ("", "")
    fake_proc.returncode = 0

    with patch.object(artifact_service.subprocess, "Popen", return_value=fake_proc) as popen:
        artifact_service._run_subprocess_with_group_kill(
            ["/bin/true"],
            cwd="/tmp",
            timeout=5,
            stage_name="test",
            mol_id="TestMol",
        )

    popen.assert_called_once()
    kwargs = popen.call_args.kwargs
    assert kwargs.get("start_new_session") is True, (
        "start_new_session must stay True — killpg depends on it"
    )
    assert kwargs.get("preexec_fn") is artifact_service._pdeathsig_preexec, (
        "preexec_fn must be _pdeathsig_preexec so the kernel kills the "
        "child when the parent uvicorn dies ungracefully"
    )


def test_pdeathsig_preexec_calls_prctl_with_sigkill_on_linux():
    """On Linux the preexec_fn must issue prctl(PR_SET_PDEATHSIG,
    SIGKILL)."""

    fake_libc = MagicMock()
    fake_libc.prctl.return_value = 0

    with (
        patch("ctypes.CDLL", return_value=fake_libc),
        patch("ctypes.util.find_library", return_value="libc.so.6"),
    ):
        artifact_service._pdeathsig_preexec()

    fake_libc.prctl.assert_called_once()
    args = fake_libc.prctl.call_args.args
    assert args[0] == 1, "first prctl arg must be PR_SET_PDEATHSIG (=1)"
    assert args[1] == signal.SIGKILL, "second prctl arg must be SIGKILL"


def test_pdeathsig_preexec_swallows_exception_on_non_linux():
    """macOS / FreeBSD dev machines don't have prctl. The preexec_fn
    must not raise — otherwise every subprocess launch crashes in the
    forked child before execve."""

    with patch("ctypes.CDLL", side_effect=OSError("libc not found")):
        # Must NOT raise.
        artifact_service._pdeathsig_preexec()


def test_pdeathsig_preexec_swallows_prctl_failure():
    """If prctl() itself fails (kernel without this feature), continue
    silently rather than crash the child."""

    fake_libc = MagicMock()
    fake_libc.prctl.side_effect = OSError("prctl not supported")

    with (
        patch("ctypes.CDLL", return_value=fake_libc),
        patch("ctypes.util.find_library", return_value="libc.so.6"),
    ):
        # Must NOT raise.
        artifact_service._pdeathsig_preexec()
