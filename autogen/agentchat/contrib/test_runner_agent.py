import subprocess
import autogen
from typing import Dict, Union


class TestRunnerAgent(autogen.UserProxyAgent):
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)

    def generate_init_message(self, *args, **kwargs) -> Union[str, Dict]:
        return (
            super().generate_init_message(*args, **kwargs)
            + """
All tests will be checked run by running the pytest CLI tool."""
        )

    def run_code(self, code, **kwargs):
        language = kwargs.get("lang")
        if language != "python":
            raise Exception(f"Unsupported lanuage {language}")
        filename = "tests/latest_tests.py"
        with open(filename, "w") as f:
            f.write(code)
        try:
            result = subprocess.run(["pytest", filename], check=True, text=True, capture_output=True)
            if result.returncode:
                logs = result.stderr

            else:
                logs = result.stdout
            return result.returncode, logs, None
        except subprocess.CalledProcessError as err:
            print(f"Tests failed with error: {err.stdout}")

            errors = "\n".join(line for line in err.stdout.split("\n") if line.startswith("\x1b[31mFAILED"))

            return err.returncode, errors, None
