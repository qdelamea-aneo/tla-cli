"""Unit tests for JavaClassTool.get_java_command.

Verifies that the per-call overrides (extra_classpath, max_heap_size,
parallel_gc) work correctly and that the base classpath is never mutated
between calls.
"""

from pathlib import Path
from unittest.mock import MagicMock

from tla_cli.tools.java import JavaClassTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tool(classpath: Path = Path("/fake/tla2tools.jar")) -> JavaClassTool:
    """Return a :class:`JavaClassTool` with mocked dependencies."""
    return JavaClassTool(
        name="TestTool",
        classpath=classpath,
        main_class="com.example.Main",
        pkg=MagicMock(),
        logger=MagicMock(),
        console=MagicMock(),
    )


# ---------------------------------------------------------------------------
# Basic command structure
# ---------------------------------------------------------------------------


def test_command_starts_with_java():
    cmd = make_tool().get_java_command()
    assert cmd[0] == "java"


def test_command_includes_cp_flag():
    cmd = make_tool().get_java_command()
    assert "-cp" in cmd


def test_command_includes_main_class():
    tool = make_tool()
    cmd = tool.get_java_command()
    assert "com.example.Main" in cmd


def test_command_includes_base_classpath():
    tool = make_tool(Path("/fake/tla2tools.jar"))
    cmd = tool.get_java_command()
    cp_index = cmd.index("-cp")
    assert "/fake/tla2tools.jar" in cmd[cp_index + 1]


def test_command_includes_default_heap():
    tool = make_tool()
    cmd = tool.get_java_command()
    assert f"-Xmx{tool.max_heap_size}" in cmd


def test_program_args_appended():
    cmd = make_tool().get_java_command(["-workers", "2", "Spec.tla"])
    assert cmd[-3:] == ["-workers", "2", "Spec.tla"]


# ---------------------------------------------------------------------------
# extra_classpath
# ---------------------------------------------------------------------------


def test_extra_classpath_appended():
    tool = make_tool(Path("/base.jar"))
    cmd = tool.get_java_command(extra_classpath=[Path("/extra.jar")])
    cp_index = cmd.index("-cp")
    cp_value = cmd[cp_index + 1]
    assert "/base.jar" in cp_value
    assert "/extra.jar" in cp_value


def test_extra_classpath_order_base_first():
    tool = make_tool(Path("/base.jar"))
    cmd = tool.get_java_command(extra_classpath=[Path("/extra.jar")])
    cp_value = cmd[cmd.index("-cp") + 1]
    assert cp_value.index("/base.jar") < cp_value.index("/extra.jar")


def test_extra_classpath_multiple_entries():
    tool = make_tool(Path("/base.jar"))
    extra = [Path("/a.jar"), Path("/b.jar")]
    cmd = tool.get_java_command(extra_classpath=extra)
    cp_value = cmd[cmd.index("-cp") + 1]
    assert "/a.jar" in cp_value
    assert "/b.jar" in cp_value


def test_extra_classpath_does_not_mutate_base():
    tool = make_tool(Path("/base.jar"))
    original_cp = list(tool.classpath)
    tool.get_java_command(extra_classpath=[Path("/extra.jar")])
    assert tool.classpath == original_cp


def test_repeated_calls_do_not_accumulate_entries():
    tool = make_tool(Path("/base.jar"))
    tool.get_java_command(extra_classpath=[Path("/extra.jar")])
    cmd = tool.get_java_command()
    cp_value = cmd[cmd.index("-cp") + 1]
    assert "/extra.jar" not in cp_value


def test_no_extra_classpath_omits_extra():
    tool = make_tool(Path("/base.jar"))
    cmd = tool.get_java_command()
    cp_value = cmd[cmd.index("-cp") + 1]
    assert cp_value == "/base.jar"


# ---------------------------------------------------------------------------
# max_heap_size override
# ---------------------------------------------------------------------------


def test_max_heap_size_override():
    tool = make_tool()
    cmd = tool.get_java_command(max_heap_size="8G")
    assert "-Xmx8G" in cmd


def test_max_heap_size_override_does_not_mutate_instance():
    tool = make_tool()
    original = tool.max_heap_size
    tool.get_java_command(max_heap_size="16G")
    assert tool.max_heap_size == original


def test_max_heap_size_default_used_when_not_provided():
    tool = make_tool()
    tool.max_heap_size = "2G"
    cmd = tool.get_java_command()
    assert "-Xmx2G" in cmd


# ---------------------------------------------------------------------------
# parallel_gc override
# ---------------------------------------------------------------------------


def test_parallel_gc_flag_added_when_true():
    cmd = make_tool().get_java_command(parallel_gc=True)
    assert "-XX:+UseParallelGC" in cmd


def test_parallel_gc_flag_absent_when_false():
    cmd = make_tool().get_java_command(parallel_gc=False)
    assert "-XX:+UseParallelGC" not in cmd


def test_parallel_gc_inherits_instance_default_false():
    tool = make_tool()
    assert tool.parallel_gc is False
    cmd = tool.get_java_command()
    assert "-XX:+UseParallelGC" not in cmd


def test_parallel_gc_inherits_instance_default_true():
    tool = make_tool()
    tool.parallel_gc = True
    cmd = tool.get_java_command()
    assert "-XX:+UseParallelGC" in cmd


def test_parallel_gc_override_does_not_mutate_instance():
    tool = make_tool()
    tool.get_java_command(parallel_gc=True)
    assert tool.parallel_gc is False
