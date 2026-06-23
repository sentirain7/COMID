"""Tests for template engine."""

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from protocols.template_engine import TemplateEngine

# Check if Jinja2 is available

HAS_JINJA2 = importlib.util.find_spec("jinja2") is not None


class TestTemplateEngine:
    """Test template engine."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def engine(self, temp_dir):
        return TemplateEngine(template_dir=temp_dir)

    def test_create_template(self, engine):
        """Test template creation."""
        template_content = "Hello {{ name }}!"
        engine.create_template("test.j2", template_content)

        assert engine.template_exists("test.j2")

    def test_render_string(self, engine):
        """Test string rendering."""
        template = "Temperature: {{ temp }} K"
        result = engine.render_string(template, {"temp": 298})

        assert "298" in result

    def test_render_file(self, engine):
        """Test file-based template rendering."""
        engine.create_template("greeting.j2", "Hello {{ name }}!")
        result = engine.render("greeting.j2", {"name": "World"})

        assert result == "Hello World!"

    def test_scientific_filter(self):
        """Test scientific notation filter."""
        result = TemplateEngine._filter_scientific(1.23e-5, 4)
        assert result == "1.2300e-05"

    def test_lammps_bool_filter(self):
        """Test LAMMPS boolean filter."""
        assert TemplateEngine._filter_lammps_bool(True) == "yes"
        assert TemplateEngine._filter_lammps_bool(False) == "no"

    def test_duration_to_steps_ps(self):
        """Test duration to steps conversion for ps."""
        # 100 ps with 1 fs timestep = 100000 steps
        steps = TemplateEngine._filter_duration_to_steps("100 ps", 1.0)
        assert steps == 100000

    def test_duration_to_steps_ns(self):
        """Test duration to steps conversion for ns."""
        # 1 ns with 1 fs timestep = 1000000 steps
        steps = TemplateEngine._filter_duration_to_steps("1 ns", 1.0)
        assert steps == 1000000

    def test_duration_to_steps_explicit(self):
        """Test duration to steps for explicit step count."""
        steps = TemplateEngine._filter_duration_to_steps("5000 steps", 1.0)
        assert steps == 5000

    def test_duration_to_ps(self):
        """Test duration to ps conversion."""
        assert TemplateEngine._filter_duration_to_ps("100 ps") == 100.0
        assert TemplateEngine._filter_duration_to_ps("1 ns") == 1000.0
        assert TemplateEngine._filter_duration_to_ps("1000 steps") == pytest.approx(1.0, rel=0.01)

    def test_list_templates(self, engine):
        """Test listing templates."""
        engine.create_template("a.j2", "A")
        engine.create_template("b.j2", "B")

        templates = engine.list_templates()
        assert "a.j2" in templates
        assert "b.j2" in templates


class TestTemplateEngineWithJinja2:
    """Test Jinja2 features if available."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def engine(self, temp_dir):
        return TemplateEngine(template_dir=temp_dir)

    def test_conditional_rendering(self, engine):
        """Test conditional template rendering."""
        template = """{% if use_npt %}NPT{% else %}NVT{% endif %}"""
        result = engine.render_string(template, {"use_npt": True})
        assert "NPT" in result

    def test_loop_rendering(self, engine):
        """Test loop template rendering."""
        template = """{% for i in range(3) %}{{ i }}{% endfor %}"""
        result = engine.render_string(template, {})
        assert "012" in result

    def test_filter_chain(self, engine):
        """Test chained filters."""
        template = """{{ value | scientific }}"""
        result = engine.render_string(template, {"value": 1.5e-3})
        assert "1.5" in result
        assert "e-03" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
