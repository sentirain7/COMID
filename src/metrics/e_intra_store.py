"""
E_intra cache store.

Provides persistent caching for intramolecular energy values
to avoid redundant calculations.
"""

import json
from datetime import datetime
from pathlib import Path

from common.logging import get_logger
from common.pathing import DEFAULT_CACHE_DIR, get_project_root
from contracts.interfaces import AbstractEIntraStore
from contracts.schemas import EIntraKey, EIntraValue

logger = get_logger("metrics.e_intra_store")


class EIntraStore(AbstractEIntraStore):
    """
    Persistent store for E_intra values.

    Caches intramolecular energies for molecules computed
    via single-molecule vacuum simulations.
    """

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize E_intra store.

        Args:
            cache_dir: Directory for cache files
        """
        if cache_dir is None:
            cache_dir = get_project_root() / DEFAULT_CACHE_DIR / "e_intra"

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self._cache: dict[str, float] = {}
        self._key_registry: dict[str, dict] = {}  # key_str -> EIntraKey fields
        self._load_cache()

    def _key_to_string(self, key: EIntraKey) -> str:
        """Convert key to string for caching (temperature-aware)."""
        return f"{key.mol_id}_{key.ff_name}_{key.ff_version}_{key.temperature_K}_{key.method}"

    def _get_cache_file(self) -> Path:
        """Get path to cache file."""
        return self.cache_dir / "e_intra_cache.json"

    def _load_cache(self) -> None:
        """Load cache from disk."""
        cache_file = self._get_cache_file()
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                self._cache = data.get("values", {})
                self._key_registry = data.get("keys", {})
                logger.info(f"Loaded {len(self._cache)} E_intra values from cache")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
                self._cache = {}
                self._key_registry = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        cache_file = self._get_cache_file()
        data = {
            "updated_at": datetime.now().isoformat(),
            "values": self._cache,
            "keys": self._key_registry,
        }
        cache_file.write_text(json.dumps(data, indent=2))

    def _legacy_key_to_string(self, key: EIntraKey) -> str:
        """Old 4-field key format (without temperature_K) for backward compat."""
        return f"{key.mol_id}_{key.ff_name}_{key.ff_version}_{key.method}"

    def get(self, key: EIntraKey) -> EIntraValue | None:
        """
        Get E_intra value from cache.

        Falls back to legacy key format (without temperature_K) for
        caches written before the temperature-aware migration.

        Args:
            key: E_intra key

        Returns:
            EIntraValue or None if not found
        """
        key_str = self._key_to_string(key)
        value = self._cache.get(key_str)

        # Fallback: try old key format for pre-migration cache entries
        if value is None:
            legacy_key = self._legacy_key_to_string(key)
            value = self._cache.get(legacy_key)
            if value is not None:
                logger.warning(
                    "E_intra file-store legacy fallback for %s: "
                    "temperature-unaware key matched. Value may not correspond "
                    "to requested %.1f K. Use DB adapter for production accuracy.",
                    key.mol_id,
                    key.temperature_K,
                )

        if value is None:
            return None
        return EIntraValue(e_intra=value, temperature_K=key.temperature_K)

    def set(self, key: EIntraKey, value: EIntraValue) -> None:
        """
        Store E_intra value in cache.

        Args:
            key: E_intra key
            value: E_intra value
        """
        key_str = self._key_to_string(key)
        self._cache[key_str] = value.e_intra
        self._key_registry[key_str] = {
            "mol_id": key.mol_id,
            "ff_name": key.ff_name,
            "ff_version": key.ff_version,
            "temperature_K": key.temperature_K,
            "method": key.method,
        }
        self._save_cache()
        logger.debug(f"Stored E_intra for {key.mol_id}: {value.e_intra:.2f} kcal/mol")

    def exists(self, key: EIntraKey) -> bool:
        """
        Check if E_intra value exists in cache.

        Args:
            key: E_intra key

        Returns:
            True if value exists
        """
        key_str = self._key_to_string(key)
        if key_str in self._cache:
            return True
        # Legacy fallback
        return self._legacy_key_to_string(key) in self._cache

    def put(self, key: EIntraKey, value: EIntraValue) -> None:
        """Store E_intra value (AbstractEIntraStore interface).

        Args:
            key: E_intra key
            value: E_intra value
        """
        self.set(key, value)

    def has(self, key: EIntraKey) -> bool:
        """Check if value exists (AbstractEIntraStore interface).

        Args:
            key: E_intra key

        Returns:
            True if value exists
        """
        return self.exists(key)

    def list_keys(self) -> list[EIntraKey]:
        """List all cached keys (AbstractEIntraStore interface).

        Returns:
            List of EIntraKey for all cached entries.
            Note: keys stored before _key_registry was introduced will
            not appear until re-set via set()/put().
        """
        keys = []
        for key_str, meta in self._key_registry.items():
            if key_str in self._cache:  # consistency check
                # Backward compat: old registry entries lack temperature_K
                meta_compat = dict(meta)
                meta_compat.setdefault("temperature_K", 298.0)
                keys.append(EIntraKey(**meta_compat))
        return keys

    def delete(self, key: EIntraKey) -> None:
        """
        Delete E_intra value from cache.

        Args:
            key: E_intra key
        """
        key_str = self._key_to_string(key)
        if key_str in self._cache:
            del self._cache[key_str]
            self._key_registry.pop(key_str, None)
            self._save_cache()

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache = {}
        self._key_registry = {}
        self._save_cache()
        logger.info("E_intra cache cleared")

    def get_all(self) -> dict[str, float]:
        """Get all cached values."""
        return dict(self._cache)

    def count(self) -> int:
        """Get number of cached values."""
        return len(self._cache)

    def get_for_molecules(
        self,
        mol_ids: list[str],
        ff_name: str,
        ff_version: str,
        temperature_K: float = 298.0,
    ) -> dict[str, float]:
        """
        Get E_intra values for multiple molecules.

        Args:
            mol_ids: List of molecule IDs
            ff_name: Force field name
            ff_version: Force field version

        Returns:
            Dictionary of mol_id -> E_intra
        """
        result = {}
        for mol_id in mol_ids:
            key = EIntraKey(
                mol_id=mol_id,
                ff_name=ff_name,
                ff_version=ff_version,
                temperature_K=temperature_K,
            )
            e_intra_value = self.get(key)
            if e_intra_value is not None:
                result[mol_id] = e_intra_value.e_intra
        return result

    def missing_molecules(
        self,
        mol_ids: list[str],
        ff_name: str,
        ff_version: str,
        temperature_K: float = 298.0,
    ) -> list[str]:
        """
        Get list of molecules missing E_intra values.

        Args:
            mol_ids: List of molecule IDs
            ff_name: Force field name
            ff_version: Force field version
            temperature_K: Temperature in Kelvin

        Returns:
            List of molecule IDs without cached E_intra
        """
        missing = []
        for mol_id in mol_ids:
            key = EIntraKey(
                mol_id=mol_id,
                ff_name=ff_name,
                ff_version=ff_version,
                temperature_K=temperature_K,
            )
            if not self.exists(key):
                missing.append(mol_id)
        return missing
