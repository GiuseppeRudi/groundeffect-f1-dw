from __future__ import annotations

# the ollama application to default create this api interface
OLLAMA_HOST = "http://localhost:11434"

# we use small model to be able to replicate also with a cpu 
LLM_MODEL_NAME = "qwen2.5:3b"

# 0.2 we don't want a modelo creative but reliable
LLM_TEMPERATURE = 0.2

# number of token in input 
LLM_NUM_CTX = 8192

# we don't send all the information in the csv files but a summary
MAX_ISSUES_IN_PROMPT = 30
MAX_FAILED_CHECKS_IN_PROMPT = 30
MAX_RI_ISSUES_IN_PROMPT = 20

# file json where all the information from data quality csv came 
LLM_INPUT_JSON = "dqa_llm_input.json"

# the instruction + json file go in the prompt 
LLM_PROMPT_TXT = "dqa_interpretation_prompt.txt"

# the union of all the md files
FULL_LLM_OUTPUT_MD = "full_llm_output.md"
