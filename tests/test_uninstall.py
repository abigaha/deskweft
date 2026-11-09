"""Run the real uninstaller against disposable files and fake process APIs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "uninstall.ps1"
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell is required for the uninstaller")
class TestUninstall(unittest.TestCase):
    def run_uninstall(self, config, processes=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile"
            codex = profile / ".codex"
            codex.mkdir(parents=True)
            path = codex / "config.toml"
            path.write_text(config, encoding="utf-8")
            install = root / "Install A"
            entries = [{"ProcessId": pid, "CommandLine": command.replace("<ROOT>", str(install))}
                       for pid, command in processes]
            (root / "processes.json").write_text(json.dumps(entries), encoding="utf-8")
            harness = root / "harness.ps1"
            harness.write_text(r'''
param($Uninstaller, $InstallRoot, $Fixture, $Result)
$ErrorActionPreference = 'Stop'
$global:fixtureProcesses = Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
$global:stoppedProcesses = [System.Collections.Generic.List[int]]::new()
function Unregister-ScheduledTask { param($TaskName, [switch]$Confirm, $ErrorAction) }
function Get-CimInstance { param($ClassName, $Filter) $global:fixtureProcesses }
function Stop-Process { param([int]$Id, [switch]$Force, $ErrorAction) $global:stoppedProcesses.Add($Id) }
& $Uninstaller -Root $InstallRoot
ConvertTo-Json -InputObject @($global:stoppedProcesses.ToArray()) | Set-Content -LiteralPath $Result
''', encoding="utf-8")
            env = dict(os.environ, USERPROFILE=str(profile))
            subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(harness),
                            str(SCRIPT), str(install), str(root / "processes.json"),
                            str(root / "result.json")], env=env, check=True,
                           capture_output=True, text=True, timeout=20)
            try:
                parsed = tomllib.loads(path.read_text(encoding="utf-8-sig"))
            except tomllib.TOMLDecodeError as error:
                self.fail(f"uninstall corrupted the remaining configuration: {error}")
            return parsed, json.loads((root / "result.json").read_text(encoding="utf-8-sig"))

    def test_removes_the_whole_server_section_in_any_position(self):
        deskweft = '[mcp_servers.deskweft]\nurl = "http://127.0.0.1:8765/mcp"\nrequired = false\n'
        other = '[mcp_servers.other]\nurl = "http://other/mcp"\n'
        last = '[mcp_servers.last]\nurl = "http://last/mcp"\n'
        for config in (deskweft + other + last, other + deskweft + last,
                       other + last + deskweft):
            with self.subTest(config=config):
                parsed, stopped = self.run_uninstall(config)
                self.assertEqual(parsed, {"mcp_servers": {
                    "other": {"url": "http://other/mcp"},
                    "last": {"url": "http://last/mcp"}}})
                self.assertEqual(stopped, [])

    def test_stops_only_the_exact_module_under_this_installation(self):
        processes = [
            (101, '"<ROOT>\\.venv\\Scripts\\python.exe" -m deskweft.server'),
            (102, '"<ROOT>\\.venv\\Scripts\\pythonw.exe" -m deskweft.server --option'),
            (201, '"C:\\Install B\\.venv\\Scripts\\python.exe" -m deskweft.server'),
            (202, '"<ROOT>\\.venv\\Scripts\\python.exe" unrelated.py deskweft.server'),
            (203, '"<ROOT>\\.venv\\Scripts\\python.exe" -m deskweft.server_backup'),
        ]
        _, stopped = self.run_uninstall('[mcp_servers.other]\nurl = "http://other/mcp"\n',
                                        processes)
        self.assertEqual(stopped, [101, 102])

    def test_removes_nested_settings_without_touching_similarly_named_servers(self):
        config = ('[mcp_servers.deskweft]\ncommand = "python"\n'
                  '[mcp_servers.deskweft.env]\nMODE = "background"\n'
                  '[mcp_servers.deskweft_backup]\nurl = "http://backup/mcp"\n')
        parsed, _ = self.run_uninstall(config)
        self.assertEqual(parsed, {"mcp_servers": {
            "deskweft_backup": {"url": "http://backup/mcp"}}})

    def test_quoted_and_spaced_keys_remove_only_the_deskweft_server(self):
        for server, nested in (
            ('mcp_servers."deskweft"', None),
            ('mcp_servers . deskweft', None),
            ('mcp_servers.deskweft', 'mcp_servers.deskweft . env'),
            ("'mcp_servers' . 'deskweft'", "'mcp_servers'.'deskweft'.'env'"),
            (' "mcp_servers"\t.\t"deskweft" ', ' "mcp_servers" . "deskweft" . "env" '),
        ):
            with self.subTest(server=server, nested=nested):
                config = ('[mcp_servers]\nparent = "keep"\n'
                          f'[{server}]\nurl = "http://local/mcp"\n')
                if nested:
                    config += f'[{nested}]\nMODE = "background"\n'
                config += ('[mcp_servers.deskweft_backup]\nurl = "http://backup/mcp"\n'
                           '[mcp_servers."deskweft.extra"]\nurl = "http://extra/mcp"\n'
                           '[mcp_servers.Deskweft]\nurl = "http://uppercase/mcp"\n')
                parsed, _ = self.run_uninstall(config)
                self.assertEqual(parsed, {"mcp_servers": {
                    "parent": "keep",
                    "deskweft_backup": {"url": "http://backup/mcp"},
                    "deskweft.extra": {"url": "http://extra/mcp"},
                    "Deskweft": {"url": "http://uppercase/mcp"}}})

    def test_indented_headers_preserve_other_tables(self):
        deskweft = '[mcp_servers.deskweft]\nurl = "http://local/mcp"\n'
        cases = [
            (deskweft + '  [mcp_servers.other]\n  url = "http://other/mcp"\n',
             {"mcp_servers": {"other": {"url": "http://other/mcp"}}}),
            (' \t[mcp_servers.deskweft]\nurl = "http://local/mcp"\n'
             '\t[mcp_servers.deskweft.env]\nMODE = "background"\n'
             '[ui]\ntheme = "dark"\n', {"ui": {"theme": "dark"}}),
            (deskweft + '\t[ui]\ntheme = "dark"\n', {"ui": {"theme": "dark"}}),
            (deskweft + ' \t[[projects]]\npath = "example"\n',
             {"projects": [{"path": "example"}]}),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                parsed, _ = self.run_uninstall(config)
                self.assertEqual(parsed, expected)

    def test_section_headers_inside_multiline_values_are_preserved(self):
        for value in ('"""\n[mcp_servers.deskweft]\nthis is a note\n"""',
                      "'''\n[mcp_servers.deskweft]\nthis is a note\n'''",
                      '"""\n[mcp_servers.deskweft]\nends in a quote""""',
                      '"""\n[mcp_servers.deskweft]\nends in two quotes"""""',
                      '[\n ["first"],\n ["last"]\n]'):
            with self.subTest(value=value):
                config = ('[mcp_servers.other]\n# Ignored quote: """\n'
                          f'notes = {value}\n'
                          '[mcp_servers.deskweft]\n'
                          'notes = """\n[ui]\nthis entire value must go\n"""\n'
                          '[ui]\ntheme = "dark"\n')
                expected = tomllib.loads(config)
                del expected["mcp_servers"]["deskweft"]
                parsed, _ = self.run_uninstall(config)
                self.assertEqual(parsed, expected)


if __name__ == "__main__":
    unittest.main()
