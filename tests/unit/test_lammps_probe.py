"""Tests for LAMMPS capability probing and optimization profiles."""

from __future__ import annotations

from contracts.schema_enums import AccelMode, KokkosBackend
from contracts.schemas import LammpsCaps
from orchestrator.lammps_probe import (
    _parse_kokkos_backend,
    _parse_kokkos_fft,
    _parse_kokkos_precision,
    _parse_packages,
    _parse_version,
    determine_accel_mode,
    get_optimization_profile,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_HELP_OUTPUT = """\
Large-scale Atomic/Molecular Massively Parallel Simulator - 22 Jul 2025 - Update 2
Git info (HEAD / stable_22Jul2025_update2)

KOKKOS package API: CUDA Serial
KOKKOS package precision: double
KOKKOS FFT engine  = mpiFFT
KOKKOS FFT library = KISS

Installed packages:

KOKKOS KSPACE MANYBODY MOLECULE REAXFF RIGID
"""

SAMPLE_HELP_OPENMP = """\
Large-scale Atomic/Molecular Massively Parallel Simulator - 2 Aug 2023
KOKKOS package API: OpenMP Serial
KOKKOS package precision: double
KOKKOS FFT library = FFTW3

Installed packages:

KOKKOS KSPACE MOLECULE
"""

SAMPLE_HELP_NO_KOKKOS = """\
Large-scale Atomic/Molecular Massively Parallel Simulator - 17 Apr 2024

Installed packages:

KSPACE MOLECULE RIGID
"""


def _make_caps(**overrides) -> LammpsCaps:
    """Create a LammpsCaps with sensible defaults, overriding as needed."""
    defaults = {
        "executable_path": "/usr/bin/lmp",
        "version_string": "22 Jul 2025",
        "installed_packages": ["KOKKOS", "KSPACE"],
        "kokkos_backend": KokkosBackend.CUDA,
        "gpu_detected": True,
        "gpu_count": 1,
        "cpu_cores": 8,
        "accel_mode": AccelMode.SERIAL,
    }
    defaults.update(overrides)
    return LammpsCaps(**defaults)


# ---------------------------------------------------------------------------
# Tests: help text parsing
# ---------------------------------------------------------------------------


class TestHelpParsing:
    def test_parse_version_cuda(self) -> None:
        assert _parse_version(SAMPLE_HELP_OUTPUT) == "22 Jul 2025"

    def test_parse_version_openmp(self) -> None:
        assert _parse_version(SAMPLE_HELP_OPENMP) == "2 Aug 2023"

    def test_parse_version_missing(self) -> None:
        assert _parse_version("no version here") == "unknown"

    def test_parse_packages_cuda(self) -> None:
        pkgs = _parse_packages(SAMPLE_HELP_OUTPUT)
        assert "KOKKOS" in pkgs
        assert "KSPACE" in pkgs
        assert "REAXFF" in pkgs

    def test_parse_packages_no_kokkos(self) -> None:
        pkgs = _parse_packages(SAMPLE_HELP_NO_KOKKOS)
        assert "KOKKOS" not in pkgs
        assert "KSPACE" in pkgs

    def test_parse_kokkos_backend_cuda(self) -> None:
        assert _parse_kokkos_backend(SAMPLE_HELP_OUTPUT) == KokkosBackend.CUDA

    def test_parse_kokkos_backend_openmp(self) -> None:
        assert _parse_kokkos_backend(SAMPLE_HELP_OPENMP) == KokkosBackend.OPENMP

    def test_parse_kokkos_backend_none(self) -> None:
        assert _parse_kokkos_backend(SAMPLE_HELP_NO_KOKKOS) == KokkosBackend.NONE

    def test_parse_kokkos_precision(self) -> None:
        assert _parse_kokkos_precision(SAMPLE_HELP_OUTPUT) == "double"

    def test_parse_kokkos_fft(self) -> None:
        assert _parse_kokkos_fft(SAMPLE_HELP_OUTPUT) == "KISS"


# ---------------------------------------------------------------------------
# Tests: AccelMode determination
# ---------------------------------------------------------------------------


class TestAccelMode:
    def test_kokkos_gpu_cuda(self) -> None:
        caps = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            gpu_detected=True,
        )
        assert determine_accel_mode(caps) == AccelMode.KOKKOS_GPU

    def test_kokkos_gpu_hip(self) -> None:
        caps = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.HIP,
            gpu_detected=True,
        )
        assert determine_accel_mode(caps) == AccelMode.KOKKOS_GPU

    def test_kokkos_cuda_no_gpu_fallback(self) -> None:
        caps = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            gpu_detected=False,
        )
        assert determine_accel_mode(caps) == AccelMode.MPI_ONLY

    def test_kokkos_openmp(self) -> None:
        caps = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.OPENMP,
            gpu_detected=False,
        )
        assert determine_accel_mode(caps) == AccelMode.KOKKOS_CPU

    def test_gpu_no_kokkos_fallback(self) -> None:
        """GPU detected but no KOKKOS → MPI_ONLY with warning."""
        caps = _make_caps(
            installed_packages=["KSPACE", "MOLECULE"],
            kokkos_backend=KokkosBackend.NONE,
            gpu_detected=True,
        )
        assert determine_accel_mode(caps) == AccelMode.MPI_ONLY

    def test_mpi_only(self) -> None:
        caps = _make_caps(
            installed_packages=["KSPACE"],
            kokkos_backend=KokkosBackend.NONE,
            gpu_detected=False,
            cpu_cores=8,
        )
        assert determine_accel_mode(caps) == AccelMode.MPI_ONLY

    def test_serial(self) -> None:
        caps = _make_caps(
            installed_packages=["KSPACE"],
            kokkos_backend=KokkosBackend.NONE,
            gpu_detected=False,
            cpu_cores=1,
        )
        assert determine_accel_mode(caps) == AccelMode.SERIAL


# ---------------------------------------------------------------------------
# Tests: optimization profile
# ---------------------------------------------------------------------------


class TestOptimizationProfile:
    def test_kokkos_gpu_profile(self) -> None:
        caps = _make_caps(accel_mode=AccelMode.KOKKOS_GPU)
        profile = get_optimization_profile(caps)

        # LAMMPS 2025+: newton off required with KOKKOS neigh full option
        assert profile["newton"] == "off"
        assert "neigh full" in profile["package_kokkos"]
        assert "comm device" in profile["package_kokkos"]
        assert profile["neigh_delay"] == 10
        assert profile["neigh_every"] == 5
        assert profile["neigh_check"] is True
        # NOTE: nvt_dump_interval/npt_dump_interval removed in v00.97.00
        # Dump intervals are now computed adaptively in protocol_chain.py
        assert "nvt_dump_interval" not in profile
        assert "npt_dump_interval" not in profile
        assert profile["dump_velocity"] is False

    def test_kokkos_cpu_profile(self) -> None:
        caps = _make_caps(accel_mode=AccelMode.KOKKOS_CPU)
        profile = get_optimization_profile(caps)

        assert profile["newton"] == "on"
        assert "neigh half" in profile["package_kokkos"]
        assert "comm host" in profile["package_kokkos"]

    def test_mpi_only_profile(self) -> None:
        caps = _make_caps(accel_mode=AccelMode.MPI_ONLY)
        profile = get_optimization_profile(caps)

        assert profile["newton"] == "on"
        assert profile["package_kokkos"] is None

    def test_serial_profile(self) -> None:
        caps = _make_caps(accel_mode=AccelMode.SERIAL)
        profile = get_optimization_profile(caps)

        assert profile["newton"] == "on"
        assert profile["package_kokkos"] is None

    def test_viscosity_keeps_velocity(self) -> None:
        caps = _make_caps(accel_mode=AccelMode.KOKKOS_GPU)
        profile = get_optimization_profile(caps)

        assert profile["dump_velocity"] is False  # NVT/NPT: no velocity
        assert profile["viscosity_dump_velocity"] is True  # viscosity: keep velocity


# ---------------------------------------------------------------------------
# Tests: LAMMPS input generator integration
# ---------------------------------------------------------------------------


class TestInputGeneratorCaps:
    """Test that LAMMPSInputGenerator respects caps."""

    def _make_generator(self, accel_mode: AccelMode):
        """Create generator with mocked caps."""
        from protocols.lammps_input import LAMMPSInputGenerator

        caps = _make_caps(accel_mode=accel_mode)
        return LAMMPSInputGenerator(caps=caps)

    def _make_generator_no_caps(self):
        from protocols.lammps_input import LAMMPSInputGenerator

        return LAMMPSInputGenerator()

    def test_no_caps_backward_compat(self) -> None:
        """Without caps, output should not contain newton or package kokkos."""
        gen = self._make_generator_no_caps()
        # Access internal method to check neighbor settings
        text = gen._generate_neighbor_settings()
        assert "package kokkos" not in text
        assert "delay 5 every 1" in text

    def test_kokkos_gpu_header_has_newton_off(self) -> None:
        """LAMMPS 2025+: newton off required with KOKKOS GPU."""
        gen = self._make_generator(AccelMode.KOKKOS_GPU)
        gen._opt_profile = get_optimization_profile(_make_caps(accel_mode=AccelMode.KOKKOS_GPU))
        from contracts.schemas import FFType, RunTier, StudyType
        from protocols.protocol_chain import ProtocolChain

        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.BULK,
            temperature_K=298.0,
            pressure_atm=1.0,
            steps=[],
        )
        header = gen._generate_header(chain)
        assert "newton off" in header

    def test_kokkos_gpu_package_commands(self) -> None:
        """LAMMPS 2025: package kokkos must be before read_data."""
        gen = self._make_generator(AccelMode.KOKKOS_GPU)
        gen._opt_profile = get_optimization_profile(_make_caps(accel_mode=AccelMode.KOKKOS_GPU))
        # package kokkos is now in _generate_package_commands() (before read_data)
        pkg_text = gen._generate_package_commands()
        assert "package kokkos neigh full comm device" in pkg_text

        # neighbor settings only has delay/every/check
        neigh_text = gen._generate_neighbor_settings()
        assert "package kokkos" not in neigh_text
        assert "delay 10 every 5" in neigh_text

    def test_mpi_only_no_package_kokkos(self) -> None:
        gen = self._make_generator(AccelMode.MPI_ONLY)
        gen._opt_profile = get_optimization_profile(_make_caps(accel_mode=AccelMode.MPI_ONLY))
        text = gen._generate_neighbor_settings()
        assert "package kokkos" not in text

    def test_flush_yes_always_present(self) -> None:
        """thermo_modify flush yes must never be removed."""
        gen = self._make_generator(AccelMode.KOKKOS_GPU)
        gen._opt_profile = get_optimization_profile(_make_caps(accel_mode=AccelMode.KOKKOS_GPU))
        from protocols.protocol_chain import ProtocolStep

        step = ProtocolStep(
            name="nvt_test",
            step_type="nvt",
            ensemble="nvt",
            duration="100 ps",
            timestep_fs=1.0,
            temperature_K=298.0,
            thermo_interval=1000,
            dump_interval=10000,
        )
        text = gen._generate_nvt(step, 0)
        assert "thermo_modify flush yes" in text


class TestProbeCacheDefenseB:
    """Defense B: a degraded probe (empty packages == lmp -h read nothing, i.e.
    it timed out under load) must NOT be written to the shared file cache — that
    would poison every worker into running LAMMPS without ``-k on``."""

    @staticmethod
    def _patch_key(monkeypatch, lp):
        monkeypatch.setattr(lp, "_cached_caps", None, raising=False)
        monkeypatch.setattr(lp, "_cached_key", None, raising=False)
        monkeypatch.setattr(lp, "_resolve_executable", lambda e: "/usr/bin/lmp")
        monkeypatch.setattr(lp.os, "stat", lambda p: type("S", (), {"st_mtime": 1.0})())
        monkeypatch.setattr(lp, "_detect_gpus", lambda: {"detected": True})

    def test_degraded_probe_not_persisted(self, monkeypatch):
        import orchestrator.lammps_probe as lp

        self._patch_key(monkeypatch, lp)
        monkeypatch.setattr(lp, "_load_file_cache", lambda key: None)
        degraded = _make_caps(
            installed_packages=[],
            kokkos_backend=KokkosBackend.NONE,
            accel_mode=AccelMode.MPI_ONLY,
        )
        monkeypatch.setattr(lp, "probe_lammps_caps", lambda *a, **k: degraded)
        saved: list = []
        monkeypatch.setattr(lp, "_save_file_cache", lambda key, caps: saved.append(caps))

        lp.get_lammps_caps("/usr/bin/lmp")
        assert saved == [], "degraded probe must not be written to the file cache"

    def test_degraded_probe_falls_back_to_existing_good_cache(self, monkeypatch):
        import orchestrator.lammps_probe as lp

        self._patch_key(monkeypatch, lp)
        good = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            accel_mode=AccelMode.KOKKOS_GPU,
        )
        # First lookup (cache-hit check) misses -> probe; second (Defense B
        # fallback) returns the preserved good cache.
        calls = {"n": 0}

        def _load(key):
            calls["n"] += 1
            return None if calls["n"] == 1 else good

        monkeypatch.setattr(lp, "_load_file_cache", _load)
        degraded = _make_caps(installed_packages=[], accel_mode=AccelMode.MPI_ONLY)
        monkeypatch.setattr(lp, "probe_lammps_caps", lambda *a, **k: degraded)
        saved: list = []
        monkeypatch.setattr(lp, "_save_file_cache", lambda key, caps: saved.append(caps))

        caps = lp.get_lammps_caps("/usr/bin/lmp")
        assert caps.accel_mode == AccelMode.KOKKOS_GPU  # returns the good cache
        assert saved == []  # still never persists the degraded result

    def test_good_probe_is_persisted(self, monkeypatch):
        import orchestrator.lammps_probe as lp

        self._patch_key(monkeypatch, lp)
        monkeypatch.setattr(lp, "_load_file_cache", lambda key: None)
        good = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            accel_mode=AccelMode.KOKKOS_GPU,
        )
        monkeypatch.setattr(lp, "probe_lammps_caps", lambda *a, **k: good)
        saved: list = []
        monkeypatch.setattr(lp, "_save_file_cache", lambda key, caps: saved.append(caps))

        lp.get_lammps_caps("/usr/bin/lmp")
        assert len(saved) == 1 and saved[0].accel_mode == AccelMode.KOKKOS_GPU


class TestProbeCacheBinaryKey:
    """v01.06.07 root-cause fix: the cache key is binary identity (path, mtime)
    ONLY — GPU availability is not in the key. A transient nvidia-smi/lmp -h
    timeout under load (reporting gpu=False) must NOT discard a good KOKKOS_GPU
    cache, which was the real cause of the mass "Package kokkos without KOKKOS"
    (and mirror "Must use 'newton off'") failures during large batches."""

    @staticmethod
    def _patch_common(monkeypatch, lp):
        monkeypatch.setattr(lp, "_cached_caps", None, raising=False)
        monkeypatch.setattr(lp, "_cached_key", None, raising=False)
        monkeypatch.setattr(lp, "_resolve_executable", lambda e: "/usr/bin/lmp")
        monkeypatch.setattr(lp.os, "stat", lambda p: type("S", (), {"st_mtime": 1.0})())

    def test_good_cache_trusted_when_gpu_probe_transiently_fails(self, monkeypatch):
        """Core fix: good KOKKOS_GPU cache is returned even when the GPU probe
        transiently reports no GPU (load timeout) — and the binary is NOT re-probed."""
        import orchestrator.lammps_probe as lp

        self._patch_common(monkeypatch, lp)
        # Simulate load: GPU probe FAILS (transient nvidia-smi/lmp -h timeout).
        monkeypatch.setattr(
            lp, "_detect_gpus", lambda: {"detected": False, "count": 0, "model": None}
        )
        good = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            accel_mode=AccelMode.KOKKOS_GPU,
        )
        monkeypatch.setattr(lp, "_load_file_cache", lambda key: good)

        def _boom(*a, **k):
            raise AssertionError("probe must NOT run when a good cache exists")

        monkeypatch.setattr(lp, "probe_lammps_caps", _boom)

        caps = lp.get_lammps_caps("/usr/bin/lmp")
        assert caps.accel_mode == AccelMode.KOKKOS_GPU

    def test_non_gpu_cache_reprobes_when_gpu_appears(self, monkeypatch):
        """Upgrade path: a non-GPU cache on a CUDA-capable KOKKOS binary IS
        re-probed once when a GPU is now present (rare hardware/driver upgrade)."""
        import orchestrator.lammps_probe as lp

        self._patch_common(monkeypatch, lp)
        monkeypatch.setattr(
            lp, "_detect_gpus", lambda: {"detected": True, "count": 1, "model": "H200"}
        )
        stale = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            accel_mode=AccelMode.MPI_ONLY,  # cache predates the GPU
        )
        monkeypatch.setattr(lp, "_load_file_cache", lambda key: stale)
        fresh = _make_caps(
            installed_packages=["KOKKOS", "KSPACE"],
            kokkos_backend=KokkosBackend.CUDA,
            accel_mode=AccelMode.KOKKOS_GPU,
        )
        monkeypatch.setattr(lp, "probe_lammps_caps", lambda *a, **k: fresh)
        monkeypatch.setattr(lp, "_save_file_cache", lambda key, caps: None)

        caps = lp.get_lammps_caps("/usr/bin/lmp")
        assert caps.accel_mode == AccelMode.KOKKOS_GPU
