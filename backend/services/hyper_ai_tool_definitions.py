"""OpenAI-compatible tool definitions for Hyper AI."""

from services.hyper_ai_subagents import SUBAGENT_TOOLS
from services.hyper_ai_tool_defs_factor import FACTOR_TOOLS
from services.hyper_ai_tool_defs_read import READ_ONLY_TOOLS
from services.hyper_ai_tool_defs_write import WRITE_TOOLS

EXTERNAL_TOOLS = [{'type': 'function',
  'function': {'name': 'web_search',
               'description': 'Search the web for quant research, market news, factor ideas, or '
                              'any external information. Use when user asks about recent events, '
                              'research papers, trading strategies from the internet, or when you '
                              'need external knowledge to design factors.',
               'parameters': {'type': 'object',
                              'properties': {'query': {'type': 'string',
                                                       'description': 'Search query (English '
                                                                      'recommended for better '
                                                                      'results)'},
                                             'max_results': {'type': 'integer',
                                                             'description': 'Max number of results '
                                                                            '(default 5, max 10)',
                                                             'default': 5}},
                              'required': ['query']}}},
 {'type': 'function',
  'function': {'name': 'fetch_url',
               'description': 'Fetch the full content of a web page and convert it to clean '
                              'Markdown text. Use AFTER web_search to retrieve detailed content '
                              'from a specific URL found in search results. Supports HTML pages, '
                              'blog posts, documentation, and GitHub files. For academic papers, '
                              'fetch the abstract page rather than the PDF directly.',
               'parameters': {'type': 'object',
                              'properties': {'url': {'type': 'string',
                                                     'description': 'The URL to fetch content '
                                                                    'from'},
                                             'max_length': {'type': 'integer',
                                                            'description': 'Maximum content length '
                                                                           'in characters (default '
                                                                           '8000, max 15000)',
                                                            'default': 8000}},
                              'required': ['url']}}}]

SKILL_TOOLS = [{'type': 'function',
  'function': {'name': 'load_skill',
               'description': 'Load a skill workflow guide into your context. This does NOT '
                              'perform any action — it provides you with step-by-step instructions '
                              "for a specific task type. Use this when a user's request matches "
                              'one of your available skills.',
               'parameters': {'type': 'object',
                              'properties': {'skill_name': {'type': 'string',
                                                            'description': 'Name of the skill to '
                                                                           'load (e.g., '
                                                                           "'prompt-strategy-setup', "
                                                                           "'trader-diagnosis')"}},
                              'required': ['skill_name']}}},
 {'type': 'function',
  'function': {'name': 'load_skill_reference',
               'description': "Load a reference document from a skill's references/ directory. Use "
                              'this when a loaded skill mentions additional reference materials '
                              'you should consult.',
               'parameters': {'type': 'object',
                              'properties': {'skill_name': {'type': 'string',
                                                            'description': 'Name of the skill'},
                                             'reference_file': {'type': 'string',
                                                                'description': 'Filename of the '
                                                                               'reference document '
                                                                               '(e.g., '
                                                                               "'signal-design-guide.md')"}},
                              'required': ['skill_name', 'reference_file']}}}]

HYPER_AI_TOOLS = (
    READ_ONLY_TOOLS
    + WRITE_TOOLS
    + FACTOR_TOOLS
    + EXTERNAL_TOOLS
    + SKILL_TOOLS
    + SUBAGENT_TOOLS
)
