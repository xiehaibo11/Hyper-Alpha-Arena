"""Program AI system prompt assembly."""

from services.ai_program_prompt_part1 import PROGRAM_SYSTEM_PROMPT_PART1
from services.ai_program_prompt_part2 import PROGRAM_SYSTEM_PROMPT_PART2

PROGRAM_SYSTEM_PROMPT = PROGRAM_SYSTEM_PROMPT_PART1 + "\n" + PROGRAM_SYSTEM_PROMPT_PART2
