import unittest
import sys
import os

# Add the generate-images directory to sys.path so we can import generate
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(repo_root, "generate-images"))

from generate import extract_commands

class TestExtractCommands(unittest.TestCase):
    def test_format_1_standard_swe_agent(self):
        traj_data = {
            "info": {
                "history": [
                    {"action": "echo hello"},
                    {"action_dict": {"command": "ls -l"}}
                ]
            }
        }
        cmds = extract_commands(traj_data)
        self.assertEqual(cmds, ["echo hello", "ls -l"])

    def test_format_2_messages_array(self):
        traj_data = {
            "messages": [
                {"role": "user", "content": "do this"},
                {"role": "assistant", "content": "Okay!\n```bash\necho hi\n```\nNext:\n```bash\npwd\n```"}
            ]
        }
        cmds = extract_commands(traj_data)
        self.assertEqual(cmds, ["echo hi", "pwd"])

    def test_format_3_openhands(self):
        traj_data = {
            "trajectory": [
                {"action": "run", "args": {"command": "git status"}},
                {"tool_calls": [{"function": {"name": "execute_bash", "arguments": '{"command": "pytest"}'}}]},
                {"command": "cat file.txt"}
            ]
        }
        cmds = extract_commands(traj_data)
        self.assertEqual(cmds, ["git status", "pytest", "cat file.txt"])

    def test_format_4_simple_list(self):
        traj_data = ["ls", "pwd"]
        cmds = extract_commands(traj_data)
        self.assertEqual(cmds, ["ls", "pwd"])

if __name__ == "__main__":
    unittest.main()
