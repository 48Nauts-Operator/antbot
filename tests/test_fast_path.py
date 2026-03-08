"""Tests for the fast-path dispatcher."""

import pytest

from antbot.agent.fast_path import FastPathRouter


@pytest.fixture
def router():
    return FastPathRouter()


WORKSPACE = "/home/user/project"


class TestFileListingPatterns:
    def test_list_files_basic(self, router):
        match = router.try_match("list files in ~/Downloads", WORKSPACE)
        assert match is not None
        assert match.tool_name == "list_dir"
        assert "Downloads" in match.arguments["path"]

    def test_ls_command(self, router):
        match = router.try_match("ls ~/Desktop", WORKSPACE)
        assert match is not None
        assert match.tool_name == "list_dir"

    def test_show_whats_in_dir(self, router):
        match = router.try_match("show me what's in /tmp", WORKSPACE)
        assert match is not None
        assert match.tool_name == "list_dir"

    def test_list_files_defaults_to_workspace(self, router):
        match = router.try_match("list files", WORKSPACE)
        assert match is not None
        assert match.tool_name == "list_dir"
        assert match.arguments["path"] == WORKSPACE


class TestFindFilePatterns:
    def test_find_py_files(self, router):
        match = router.try_match("find .py files in ~/src", WORKSPACE)
        assert match is not None
        assert match.tool_name == "exec"
        assert "*.py" in match.arguments["command"]

    def test_show_all_pdf_files(self, router):
        match = router.try_match("show all PDF files in ~/Documents", WORKSPACE)
        assert match is not None
        assert match.tool_name == "exec"
        assert "pdf" in match.arguments["command"].lower()


class TestGitPatterns:
    def test_git_status(self, router):
        match = router.try_match("git status", WORKSPACE)
        assert match is not None
        assert match.tool_name == "git"
        assert match.arguments["action"] == "status"

    def test_git_log(self, router):
        match = router.try_match("show recent commits", WORKSPACE)
        assert match is not None
        assert match.tool_name == "git"
        assert match.arguments["action"] == "log"

    def test_git_diff(self, router):
        match = router.try_match("what changed?", WORKSPACE)
        assert match is not None
        assert match.tool_name == "git"
        assert match.arguments["action"] == "diff"

    def test_git_branch(self, router):
        match = router.try_match("list branches", WORKSPACE)
        assert match is not None
        assert match.tool_name == "git"
        assert match.arguments["action"] == "branch"


class TestDockerPatterns:
    def test_docker_ps(self, router):
        match = router.try_match("show running containers", WORKSPACE)
        assert match is not None
        assert match.tool_name == "docker"
        assert match.arguments["action"] == "ps"

    def test_docker_ps_command(self, router):
        match = router.try_match("docker ps", WORKSPACE)
        assert match is not None
        assert match.tool_name == "docker"

    def test_docker_logs(self, router):
        match = router.try_match("docker logs myapp", WORKSPACE)
        assert match is not None
        assert match.tool_name == "docker"
        assert match.arguments["action"] == "logs"
        assert match.arguments["container"] == "myapp"


class TestPortPatterns:
    def test_whats_using_port(self, router):
        match = router.try_match("what's using port 8080", WORKSPACE)
        assert match is not None
        assert "8080" in str(match.arguments)

    def test_show_listening_ports(self, router):
        match = router.try_match("show listening ports", WORKSPACE)
        assert match is not None
        assert match.tool_name == "process"
        assert match.arguments["action"] == "ports"


class TestProcessPatterns:
    def test_is_nginx_running(self, router):
        match = router.try_match("is nginx running?", WORKSPACE)
        assert match is not None
        assert match.tool_name == "process"
        assert match.arguments["action"] == "check"
        assert match.arguments["name"] == "nginx"


class TestSpaceAntPatterns:
    def test_space_ant_keyword(self, router):
        match = router.try_match("space ant", WORKSPACE)
        assert match is not None
        assert match.tool_name == "space_ant"
        assert match.arguments["action"] == "scan"

    def test_check_disk_space(self, router):
        match = router.try_match("check disk space", WORKSPACE)
        assert match is not None
        assert match.tool_name == "space_ant"

    def test_whats_eating_my_disk(self, router):
        match = router.try_match("what's eating my disk", WORKSPACE)
        assert match is not None
        assert match.tool_name == "space_ant"

    def test_clean_up_space(self, router):
        """'clean up space' should trigger space_ant despite 'clean' being a write word."""
        match = router.try_match("clean up space", WORKSPACE)
        assert match is not None
        assert match.tool_name == "space_ant"

    def test_free_up_disk(self, router):
        match = router.try_match("free up disk space", WORKSPACE)
        assert match is not None
        assert match.tool_name == "space_ant"


class TestDiskUsagePatterns:
    def test_how_big_is(self, router):
        match = router.try_match("how big is ~/node_modules", WORKSPACE)
        assert match is not None
        assert match.tool_name == "exec"
        assert "du" in match.arguments["command"]

    def test_disk_usage_of(self, router):
        match = router.try_match("disk usage of ~/Projects", WORKSPACE)
        assert match is not None
        assert "du" in match.arguments["command"]


class TestSystemInfoPatterns:
    def test_uptime(self, router):
        match = router.try_match("uptime", WORKSPACE)
        assert match is not None
        assert match.tool_name == "exec"
        assert "uptime" in match.arguments["command"]

    def test_how_much_ram(self, router):
        match = router.try_match("how much RAM do I have?", WORKSPACE)
        assert match is not None
        assert match.tool_name == "exec"


class TestWriteIntentGate:
    """Messages with write intent should NOT match (return None)."""

    def test_sort_files_skipped(self, router):
        assert router.try_match("sort files in ~/Downloads by date", WORKSPACE) is None

    def test_delete_files_skipped(self, router):
        assert router.try_match("delete old files in /tmp", WORKSPACE) is None

    def test_rename_file_skipped(self, router):
        assert router.try_match("rename file.txt to file2.txt", WORKSPACE) is None

    def test_create_directory_skipped(self, router):
        assert router.try_match("create a new directory called src", WORKSPACE) is None

    def test_move_files_skipped(self, router):
        assert router.try_match("move files from ~/Downloads to ~/Documents", WORKSPACE) is None

    def test_install_skipped(self, router):
        assert router.try_match("install numpy", WORKSPACE) is None


class TestFallthrough:
    """Messages that don't match any pattern should return None."""

    def test_complex_question(self, router):
        assert router.try_match("explain this error log and suggest a fix", WORKSPACE) is None

    def test_empty_message(self, router):
        assert router.try_match("", WORKSPACE) is None

    def test_very_long_message(self, router):
        long_msg = "list files in ~/Downloads " + "and also " * 50
        assert router.try_match(long_msg, WORKSPACE) is None

    def test_conversational(self, router):
        assert router.try_match("hello, how are you?", WORKSPACE) is None

    def test_code_question(self, router):
        assert router.try_match("how do I write a Python function?", WORKSPACE) is None
