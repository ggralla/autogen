from typing import List, Optional
from autogen.agentchat.conversable_agent import ConversableAgent

import re
import pandas as pd


class DiscoveryAgent(ConversableAgent):
    def __init__(
        self,
        name: Optional[str] = "discoveryagent",
        system_message: Optional[str] = None,
        **kwargs,
    ):
        if not system_message:
            system_message = """You are a data analyst and software engineer, who is an expert on how to write python functions to analyze complex data.
            You are very curious, a meticulous planner, and are good at using basic skills to solve complex problems.
            When you are asked for ideas, always respond with a numbered list."""

        super().__init__(name, system_message=system_message, **kwargs)

        self.generated_ideas = []
        self.df: Optional[pd.DataFrame] = None

    # Parse text containing a numbered list. Returns a list of strings

    def extract_numbered_list(self, response_text: str):
        # Matches any line that starts with a number followed by a dot and a space
        pattern = r"\d+\.\s+(.*?)\n(?=\d+\.|\Z)"
        matches = re.findall(pattern, response_text, re.DOTALL)
        return matches

    def generate_reply(self, **kwargs):
        ret = super().generate_reply(**kwargs)
        self.generated_ideas = self.extract_numbered_list(ret)
        return ret

    def load_data(self, filename):
        self.df = pd.read_csv(filename)
        return self.df

    def describe_data(self):
        if self.df is None:
            raise ValueError("No data loaded")
        description = f"""The dataset has the following columns: {', '.join(self.df.columns)}.
                        Sample data: {self.df.head(5)}"""
        return description
