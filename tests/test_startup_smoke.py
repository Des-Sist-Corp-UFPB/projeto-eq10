import subprocess
import unittest
from unittest.mock import patch

from scripts import smoke_test_startup_container as smoke


class TestStartupSmokeProcessLookup(unittest.TestCase):
    def test_uses_component_pid_file_instead_of_proc_scan(self):
        script = smoke._process_signal_script("uvicorn")

        self.assertIn("/tmp/eq10-uvicorn.pid", script)
        self.assertIn("uvicorn", script)
        self.assertNotIn("os.listdir('/proc')", script)
        self.assertIn("raw.isdigit()", script)
        self.assertIn("pid==os.getpid()", script)
        self.assertIn("expected not in args", script)

    def test_all_components_have_deterministic_pid_files(self):
        self.assertEqual(
            smoke.PID_FILES,
            {
                "uvicorn": "/tmp/eq10-uvicorn.pid",
                "nginx": "/tmp/eq10-nginx.pid",
            },
        )

    def test_unknown_component_is_rejected_locally(self):
        with self.assertRaisesRegex(ValueError, "unknown_component"):
            smoke._process_signal_script("other")

    @patch.object(smoke, "_run")
    def test_verified_process_is_signaled(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=(
                "PROCESS_LOOKUP | component=uvicorn | "
                "status=verified | pid=42\n"
            ), stderr=""
        )

        smoke._signal_process("uvicorn")

        command = run.call_args.args
        self.assertEqual(command[:4], ("docker", "exec", smoke.CONTAINER_NAME, "/app/.venv/bin/python"))
        self.assertNotIn("os.listdir('/proc')", command[-1])

    @patch.object(smoke, "_run")
    def test_missing_pid_file_fails_clearly(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=3, stdout=(
                "PROCESS_LOOKUP | component=uvicorn | status=not_found\n"
            ), stderr=""
        )

        with self.assertRaisesRegex(RuntimeError, "process_lookup_failed:uvicorn"):
            smoke._signal_process("uvicorn")

    def test_safe_failure_categories_cover_stale_and_wrong_component(self):
        script = smoke._process_signal_script("uvicorn")

        self.assertIn("status=stale", script)
        self.assertIn("status=wrong_component", script)
        self.assertNotIn("print(args)", script)
        self.assertNotIn("cmdline.decode", script)

    @patch.object(smoke.time, "sleep", return_value=None)
    @patch.object(smoke, "_container_health_status", side_effect=["starting", "healthy"])
    def test_waits_until_docker_reports_healthy(self, health_status, _sleep):
        smoke._wait_for_container_health(timeout=5)

        self.assertEqual(health_status.call_count, 2)

    @patch.object(smoke, "_container_health_status", return_value="unhealthy")
    def test_fails_when_docker_reports_unhealthy(self, _health_status):
        with self.assertRaisesRegex(RuntimeError, "container_health_failed:unhealthy"):
            smoke._wait_for_container_health(timeout=5)


if __name__ == "__main__":
    unittest.main()
