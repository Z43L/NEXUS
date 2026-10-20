import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import onram_cli

class StrataLaunchTests(unittest.TestCase):
    def test_launch_selects_installed_strata_without_llama_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'third_party/strata'
            runtime.mkdir(parents=True)
            config = runtime / 'strata-q2_0.json'
            config.write_text('{}')
            process = MagicMock()
            process.poll.return_value = None
            with patch.object(onram_cli, 'ROOT', root), \
                 patch.object(onram_cli, 'check_onram', side_effect=[RuntimeError('down'), 'qwen']), \
                 patch.object(onram_cli.subprocess, 'Popen', return_value=process) as start:
                onram_cli.ensure_local_server(onram_cli.DEFAULT_BASE_URL)
            command = start.call_args.args[0]
            self.assertEqual(command[command.index('--backend') + 1], 'strata')
            self.assertEqual(command[command.index('--strata-config') + 1], str(config))
