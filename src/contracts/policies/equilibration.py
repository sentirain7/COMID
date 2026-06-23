"""
Equilibration policy - SSOT for high-temperature/high-pressure equilibration settings.

This policy defines default values for enhanced equilibration protocols
used to overcome kinetic trapping in low-temperature MD simulations.

Literature references:
- Scientific Reports 2021: NPT @ 100 atm (200 ps) -> NPT @ 1 atm (1000 ps)
- ACS Omega 2022: NVT @ 800K (100 ps) -> NPT @ 200 atm, 800K (500 ps) -> gradual cooling
"""

from pydantic import BaseModel, Field


class EquilibrationPolicy(BaseModel):
    """Policy for high-temperature/high-pressure equilibration.

    Default values are based on literature minimum recommendations:
    - High temperature: 500K (literature range: 500-800K)
    - High pressure: 100 atm (literature range: 100-200 atm)
    """

    # High-temperature NVT stage defaults
    high_temp_nvt_temperature_K: float = Field(
        500.0, description="High-temperature NVT stage temperature (K)"
    )
    high_temp_nvt_duration_ps: float = Field(
        100.0, description="High-temperature NVT stage duration (ps)"
    )

    # High-pressure NPT stage defaults
    high_pressure_npt_temperature_K: float = Field(
        500.0, description="High-pressure NPT stage temperature (K)"
    )
    high_pressure_npt_pressure_atm: float = Field(
        100.0, description="High-pressure NPT stage pressure (atm)"
    )
    high_pressure_npt_duration_ps: float = Field(
        200.0, description="High-pressure NPT stage duration (ps)"
    )

    # Validation bounds
    temperature_min_K: float = Field(300.0, description="Minimum allowed temperature (K)")
    temperature_max_K: float = Field(1000.0, description="Maximum allowed temperature (K)")
    pressure_min_atm: float = Field(50.0, description="Minimum allowed pressure (atm)")
    pressure_max_atm: float = Field(500.0, description="Maximum allowed pressure (atm)")
    duration_min_ps: float = Field(50.0, description="Minimum allowed duration (ps)")
    duration_max_ps: float = Field(1000.0, description="Maximum allowed duration (ps)")

    def get_defaults_dict(self) -> dict:
        """Return default equilibration settings as a dictionary.

        Returns:
            Dictionary with default equilibration settings for frontend/API consumption.
        """
        return {
            "enabled": False,
            "high_temp_nvt_temperature_K": self.high_temp_nvt_temperature_K,
            "high_temp_nvt_duration_ps": self.high_temp_nvt_duration_ps,
            "high_pressure_npt_temperature_K": self.high_pressure_npt_temperature_K,
            "high_pressure_npt_pressure_atm": self.high_pressure_npt_pressure_atm,
            "high_pressure_npt_duration_ps": self.high_pressure_npt_duration_ps,
        }

    def get_bounds_dict(self) -> dict:
        """Return validation bounds as a dictionary.

        Returns:
            Dictionary with min/max bounds for frontend validation.
        """
        return {
            "temperature_K": {
                "min": self.temperature_min_K,
                "max": self.temperature_max_K,
            },
            "pressure_atm": {
                "min": self.pressure_min_atm,
                "max": self.pressure_max_atm,
            },
            "duration_ps": {
                "min": self.duration_min_ps,
                "max": self.duration_max_ps,
            },
        }


# SSOT: Single source of truth for equilibration policy
DEFAULT_EQUILIBRATION_POLICY = EquilibrationPolicy()
