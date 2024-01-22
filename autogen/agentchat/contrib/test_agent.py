from typing import List, Optional
from autogen.agentchat.conversable_agent import ConversableAgent

import re
import pandas as pd


class TestAgent(ConversableAgent):
    def __init__(
        self,
        name: Optional[str] = "testagent",
        system_message: Optional[str] = None,
        **kwargs,
    ):
        if not system_message:
            system_message = """You are a software engineer, who is an expert on how to write python tests using pytest.
            You are very meticulous, and always write through tests for code. You make sure to write tests that cover all funcitonality, and avoid using mocks when integration tests are possible."""

        super().__init__(name, system_message=system_message, **kwargs)
