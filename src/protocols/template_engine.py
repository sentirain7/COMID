"""
Template engine for LAMMPS input generation.

Uses Jinja2 for flexible template rendering with
LAMMPS-specific filters and functions.
"""

import re
from pathlib import Path
from typing import Any

from common.logging import get_logger

logger = get_logger("protocols.template_engine")

# Optional Jinja2 import
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


class TemplateEngine:
    """
    Jinja2-based template engine for LAMMPS scripts.

    Provides specialized filters and macros for MD simulations.
    """

    def __init__(self, template_dir: Path | None = None):
        """
        Initialize template engine.

        Args:
            template_dir: Directory containing template files.
                         If None, uses default templates directory.
        """
        if template_dir is None:
            template_dir = Path(__file__).parent.parent / "templates"

        self.template_dir = Path(template_dir)
        self.template_dir.mkdir(parents=True, exist_ok=True)

        if HAS_JINJA2:
            self.env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=select_autoescape(enabled_extensions=()),
                trim_blocks=True,
                lstrip_blocks=True,
            )
            self._register_filters()
            self._register_globals()
        else:
            self.env = None  # type: ignore[assignment]
            logger.warning("Jinja2 not installed, using simple template replacement")

    def _register_filters(self) -> None:
        """Register custom Jinja2 filters."""
        self.env.filters["scientific"] = self._filter_scientific
        self.env.filters["lammps_bool"] = self._filter_lammps_bool
        self.env.filters["duration_to_steps"] = self._filter_duration_to_steps
        self.env.filters["duration_to_ps"] = self._filter_duration_to_ps

    def _register_globals(self) -> None:
        """Register global functions available in templates."""
        self.env.globals["range"] = range
        self.env.globals["len"] = len

    @staticmethod
    def _filter_scientific(value: float, precision: int = 6) -> str:
        """Format number in scientific notation."""
        return f"{value:.{precision}e}"

    @staticmethod
    def _filter_lammps_bool(value: bool) -> str:
        """Convert Python bool to LAMMPS yes/no."""
        return "yes" if value else "no"

    @staticmethod
    def _filter_duration_to_steps(duration: str, timestep_fs: float = 1.0) -> int:
        """Convert duration string to number of steps."""
        duration = duration.strip()

        if "step" in duration.lower():
            # Already in steps
            match = re.match(r"(\d+)", duration)
            if match:
                return int(match.group(1))
            return 0

        if duration.endswith(" ps") or (duration.endswith("ps") and "step" not in duration):
            # Convert ps to steps
            value_str = duration.replace("ps", "").strip()
            ps = float(value_str)
            return int(ps * 1000 / timestep_fs)  # ps -> fs -> steps

        if duration.endswith(" ns") or duration.endswith("ns"):
            # Convert ns to steps
            value_str = duration.replace("ns", "").strip()
            ns = float(value_str)
            return int(ns * 1e6 / timestep_fs)  # ns -> fs -> steps

        # Try to parse as plain number (assume ps)
        try:
            return int(float(duration) * 1000 / timestep_fs)
        except ValueError:
            return 0

    @staticmethod
    def _filter_duration_to_ps(duration: str) -> float:
        """Convert duration string to picoseconds."""
        duration = duration.strip()

        if duration.endswith(" ps") or (duration.endswith("ps") and "step" not in duration):
            return float(duration.replace("ps", "").strip())

        if duration.endswith(" ns") or duration.endswith("ns"):
            return float(duration.replace("ns", "").strip()) * 1000

        if "step" in duration.lower():
            # Assume 1 fs timestep
            match = re.match(r"(\d+)", duration)
            if match:
                return int(match.group(1)) * 0.001
            return 0

        # Assume ps
        try:
            return float(duration)
        except ValueError:
            return 0

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        """
        Render a template with given context.

        Args:
            template_name: Name of template file (e.g., "minimize.j2")
            context: Dictionary of variables for template

        Returns:
            Rendered template string
        """
        if self.env:
            template = self.env.get_template(template_name)
            return template.render(**context)
        else:
            return self._simple_render(template_name, context)

    def render_string(self, template_str: str, context: dict[str, Any]) -> str:
        """
        Render a template string directly.

        Args:
            template_str: Template string with Jinja2 syntax
            context: Dictionary of variables for template

        Returns:
            Rendered string
        """
        if self.env:
            template = self.env.from_string(template_str)
            return template.render(**context)
        else:
            return self._simple_string_render(template_str, context)

    def _simple_render(self, template_name: str, context: dict[str, Any]) -> str:
        """Simple template rendering without Jinja2."""
        template_path = self.template_dir / template_name
        if template_path.exists():
            content = template_path.read_text()
            return self._simple_string_render(content, context)
        else:
            logger.error(f"Template not found: {template_path}")
            return ""

    def _simple_string_render(self, template_str: str, context: dict[str, Any]) -> str:
        """Simple string replacement without Jinja2."""
        result = template_str
        for key, value in context.items():
            result = result.replace("{{ " + key + " }}", str(value))
            result = result.replace("{{" + key + "}}", str(value))
        return result

    def template_exists(self, template_name: str) -> bool:
        """Check if a template file exists."""
        return (self.template_dir / template_name).exists()

    def list_templates(self) -> list[str]:
        """List all available templates."""
        return [f.name for f in self.template_dir.glob("*.j2")]

    def create_template(self, name: str, content: str) -> Path:
        """
        Create a new template file.

        Args:
            name: Template name (e.g., "custom.j2")
            content: Template content

        Returns:
            Path to created template
        """
        template_path = self.template_dir / name
        template_path.write_text(content)
        return template_path
