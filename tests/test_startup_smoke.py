import subprocess
import unittest
from unittest.mock import patch

from scripts import smoke_test_startup_container as smoke


class TestStartupSmokeProcessLookup(unittest.TestCase):
    def test_uses_component_pid_file_instead_of_proc_scan(self):
        script = smoke._process_signal_script("readiness")

        self.assertIn("/tmp/eq10-readiness.pid", script)
        self.assertIn("src.diagnostics.readiness_server", script)
        self.assertNotIn("os.listdir('/proc')", script)
        self.assertIn("raw.isdigit()", script)
        self.assertIn("pid==os.getpid()", script)
        self.assertIn("expected not in args", script)

    def test_all_components_have_deterministic_pid_files(self):
        self.assertEqual(
            smoke.PID_FILES,
            {
                "readiness": "/tmp/eq10-readiness.pid",
                "streamlit": "/tmp/eq10-streamlit.pid",
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
                "PROCESS_LOOKUP | component=readiness | "
                "status=verified | pid=42\n"
            ), stderr=""
        )

        smoke._signal_process("readiness")

        command = run.call_args.args
        self.assertEqual(command[:4], ("docker", "exec", smoke.CONTAINER_NAME, "/app/.venv/bin/python"))
        self.assertNotIn("os.listdir('/proc')", command[-1])

    @patch.object(smoke, "_run")
    def test_missing_pid_file_fails_clearly(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=3, stdout=(
                "PROCESS_LOOKUP | component=readiness | status=not_found\n"
            ), stderr=""
        )

        with self.assertRaisesRegex(RuntimeError, "process_lookup_failed:readiness"):
            smoke._signal_process("readiness")

    def test_safe_failure_categories_cover_stale_and_wrong_component(self):
        script = smoke._process_signal_script("streamlit")

        self.assertIn("status=stale", script)
        self.assertIn("status=wrong_component", script)
        self.assertNotIn("print(args)", script)
        self.assertNotIn("cmdline.decode", script)


if __name__ == "__main__":
    unittest.main()
