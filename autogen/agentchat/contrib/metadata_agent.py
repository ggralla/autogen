from typing import List, Optional, Tuple, Union, Dict, Any
from autogen import Agent, ConversableAgent

import pandas as pd


class MetadataAgent(ConversableAgent):
    def __init__(
        self,
        filename: str,
        name: Optional[str] = "metadataagent",
        system_message: Optional[str] = None,
        **kwargs,
    ):
        if not system_message:
            system_message = """You are a data analyst, software engineer, and technical writer who is an expert on how to analyze and document complex data.
            You are very thorough writer, and are good at inferring what type of data is contained by its column names and data types.
            Think step by step, and explain your thought process in detail."""

        super().__init__(name, system_message=system_message, **kwargs)

        self.df = pd.read_csv(filename)
        self.register_reply(Agent, MetadataAgent._generate_metadata)

    def _generate_metadata(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[Agent] = None,
        config: Optional[Any] = None,
    ) -> Tuple[bool, Union[Dict, None]]:
        """Generate metadata for the dataset"""

        # Add columns and sample data
        messages += [{"role": "user", "content": self.describe_data()}]

        return self.generate_oai_reply(messages, sender, config)

    def describe_data(self):
        if self.df is None:
            raise ValueError("No data loaded")
        description = f"""The dataset has the following columns: {', '.join(self.df.columns)}.
                        Sample data: {self.df.head(5)}"""
        return description
