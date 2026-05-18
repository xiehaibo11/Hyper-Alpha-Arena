"""Mutation and binding Hyper AI tool definitions."""

WRITE_TOOLS = [{'type': 'function',
  'function': {'name': 'save_signal_pool',
               'description': 'Create a signal pool from complete signal configuration. '
                              'Automatically creates signal definitions and combines them into a '
                              'pool.',
               'parameters': {'type': 'object',
                              'properties': {'pool_name': {'type': 'string',
                                                           'description': 'Display name for the '
                                                                          'pool'},
                                             'symbol': {'type': 'string',
                                                        'description': 'Symbol to monitor (e.g., '
                                                                       'BTC, ETH)'},
                                             'signals': {'type': 'array',
                                                         'items': {'type': 'object',
                                                                   'properties': {'metric': {'type': 'string',
                                                                                             'description': 'Metric '
                                                                                                            'name. '
                                                                                                            'Standard: '
                                                                                                            'cvd, '
                                                                                                            'oi_delta_percent, '
                                                                                                            'order_imbalance, '
                                                                                                            'taker_volume, '
                                                                                                            'price_change, '
                                                                                                            'volatility. '
                                                                                                            'Factor: '
                                                                                                            'factor:<name> '
                                                                                                            '(e.g., '
                                                                                                            'factor:RSI21, '
                                                                                                            'factor:ADX14).'},
                                                                                  'operator': {'type': 'string',
                                                                                               'description': 'Comparison '
                                                                                                              'operator '
                                                                                                              '(greater_than, '
                                                                                                              'less_than, '
                                                                                                              'etc.). '
                                                                                                              'NOT '
                                                                                                              'used '
                                                                                                              'for '
                                                                                                              'taker_volume.'},
                                                                                  'threshold': {'type': 'number',
                                                                                                'description': 'Threshold '
                                                                                                               'value. '
                                                                                                               'NOT '
                                                                                                               'used '
                                                                                                               'for '
                                                                                                               'taker_volume.'},
                                                                                  'time_window': {'type': 'string',
                                                                                                  'description': 'Time '
                                                                                                                 'window '
                                                                                                                 '(e.g., '
                                                                                                                 '5m, '
                                                                                                                 '15m, '
                                                                                                                 '1h)'},
                                                                                  'direction': {'type': 'string',
                                                                                                'enum': ['buy',
                                                                                                         'sell',
                                                                                                         'any'],
                                                                                                'description': 'taker_volume '
                                                                                                               'ONLY: '
                                                                                                               'dominant '
                                                                                                               'side'},
                                                                                  'ratio_threshold': {'type': 'number',
                                                                                                      'description': 'taker_volume '
                                                                                                                     'ONLY: '
                                                                                                                     'buy/sell '
                                                                                                                     'ratio '
                                                                                                                     'multiplier '
                                                                                                                     '(e.g., '
                                                                                                                     '1.5 '
                                                                                                                     '= '
                                                                                                                     '50% '
                                                                                                                     'more)'},
                                                                                  'volume_threshold': {'type': 'number',
                                                                                                       'description': 'taker_volume '
                                                                                                                      'ONLY: '
                                                                                                                      'minimum '
                                                                                                                      'total '
                                                                                                                      'volume '
                                                                                                                      'in '
                                                                                                                      'USD'}}},
                                                         'description': 'Array of signal '
                                                                        'conditions. Standard '
                                                                        'signals use '
                                                                        'metric/operator/threshold/time_window. '
                                                                        'taker_volume uses '
                                                                        'metric/direction/ratio_threshold/volume_threshold/time_window '
                                                                        'instead.'},
                                             'logic': {'type': 'string',
                                                       'enum': ['AND', 'OR'],
                                                       'description': 'Logic operator (default: '
                                                                      'AND)'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance'],
                                                          'description': 'Exchange (default: '
                                                                         'hyperliquid)'},
                                             'description': {'type': 'string',
                                                             'description': 'Optional description '
                                                                            'for the pool'}},
                              'required': ['pool_name', 'symbol', 'signals']}}},
 {'type': 'function',
  'function': {'name': 'save_prompt',
               'description': 'Create or update a trading prompt template.',
               'parameters': {'type': 'object',
                              'properties': {'prompt_id': {'type': 'integer',
                                                           'description': 'Prompt ID to update '
                                                                          '(omit for create)'},
                                             'name': {'type': 'string',
                                                      'description': 'Display name'},
                                             'description': {'type': 'string',
                                                             'description': 'Brief description'},
                                             'template_text': {'type': 'string',
                                                               'description': 'Main prompt '
                                                                              'content'}},
                              'required': ['name', 'template_text']}}},
 {'type': 'function',
  'function': {'name': 'save_program',
               'description': 'Create or update a trading program.',
               'parameters': {'type': 'object',
                              'properties': {'program_id': {'type': 'integer',
                                                            'description': 'Program ID to update '
                                                                           '(omit for create)'},
                                             'name': {'type': 'string',
                                                      'description': 'Display name'},
                                             'description': {'type': 'string',
                                                             'description': 'Brief description'},
                                             'code': {'type': 'string',
                                                      'description': 'Python strategy code'}},
                              'required': ['name', 'code']}}},
 {'type': 'function',
  'function': {'name': 'create_ai_trader',
               'description': 'Create a new AI Trader with LLM config. Tests LLM connection before '
                              'saving. Strategy binding and wallet setup are done separately.',
               'parameters': {'type': 'object',
                              'properties': {'name': {'type': 'string',
                                                      'description': 'Display name for the trader'},
                                             'model': {'type': 'string',
                                                       'description': 'LLM model name (e.g., '
                                                                      'gpt-4o, deepseek-v4-flash, '
                                                                      'claude-3.5-sonnet)'},
                                             'base_url': {'type': 'string',
                                                          'description': 'LLM API base URL (e.g., '
                                                                         'https://api.openai.com/v1)'},
                                             'api_key': {'type': 'string',
                                                         'description': 'LLM API key'}},
                              'required': ['name', 'model', 'base_url', 'api_key']}}},
 {'type': 'function',
  'function': {'name': 'list_traders',
               'description': 'List all AI Traders with bindings, strategies, wallet and trading '
                              "status. Pass trader_id to get one trader's full detail.",
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'Optional: specific AI '
                                                                          'Trader ID for detail '
                                                                          'view'}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'list_signal_pools',
               'description': 'List all signal pools with IDs, symbols, exchange, and trigger '
                              "conditions. Pass pool_id to get one pool's full detail.",
               'parameters': {'type': 'object',
                              'properties': {'pool_id': {'type': 'integer',
                                                         'description': 'Optional: specific signal '
                                                                        'pool ID for detail view'}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'list_strategies',
               'description': 'List all trading prompts and programs with IDs, names, and binding '
                              'status. Pass strategy_id + strategy_type to get full content.',
               'parameters': {'type': 'object',
                              'properties': {'strategy_id': {'type': 'integer',
                                                             'description': 'Optional: specific '
                                                                            'strategy ID for '
                                                                            'detail view'},
                                             'strategy_type': {'type': 'string',
                                                               'enum': ['prompt', 'program'],
                                                               'description': 'Required when '
                                                                              'strategy_id is '
                                                                              'provided'}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'bind_prompt_to_trader',
               'description': 'Bind a prompt template to an AI Trader (one-to-one, replaces '
                              'existing binding).',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID'},
                                             'prompt_id': {'type': 'integer',
                                                           'description': 'Prompt template ID to '
                                                                          'bind'}},
                              'required': ['trader_id', 'prompt_id']}}},
 {'type': 'function',
  'function': {'name': 'bind_program_to_trader',
               'description': 'Create a program binding for an AI Trader with trigger config '
                              '(many-to-many). IMPORTANT: exchange must match signal_pool '
                              'exchange.',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID'},
                                             'program_id': {'type': 'integer',
                                                            'description': 'Trading program ID'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance'],
                                                          'description': 'Exchange to trade on '
                                                                         '(REQUIRED). Must match '
                                                                         'signal_pool exchange.'},
                                             'signal_pool_ids': {'type': 'array',
                                                                 'items': {'type': 'integer'},
                                                                 'description': 'Signal pool IDs '
                                                                                'for triggering. '
                                                                                'Their exchange '
                                                                                'must match the '
                                                                                'binding '
                                                                                'exchange.'},
                                             'trigger_interval': {'type': 'integer',
                                                                  'description': 'Scheduled '
                                                                                 'trigger interval '
                                                                                 'in seconds '
                                                                                 '(default: 180)'},
                                             'is_active': {'type': 'boolean',
                                                           'description': 'Whether binding is '
                                                                          'active (default: '
                                                                          'true)'}},
                              'required': ['trader_id', 'program_id', 'exchange']}}},
 {'type': 'function',
  'function': {'name': 'update_trader_strategy',
               'description': 'Update trigger configuration for a Prompt-based AI Trader (signal '
                              'pools, scheduled trigger, interval, exchange).',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance'],
                                                          'description': 'Target exchange. MUST '
                                                                         "match the trader's "
                                                                         'wallet exchange.'},
                                             'signal_pool_ids': {'type': 'array',
                                                                 'items': {'type': 'integer'},
                                                                 'description': 'Signal pool IDs '
                                                                                'to bind'},
                                             'scheduled_trigger_enabled': {'type': 'boolean',
                                                                           'description': 'Enable '
                                                                                          'scheduled '
                                                                                          'trigger'},
                                             'trigger_interval': {'type': 'integer',
                                                                  'description': 'Trigger interval '
                                                                                 'in seconds'}},
                              'required': ['trader_id']}}},
 {'type': 'function',
  'function': {'name': 'update_ai_trader',
               'description': 'Update AI Trader settings (name, LLM config). Tests LLM connection '
                              'if model/base_url/api_key changes.',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID'},
                                             'name': {'type': 'string',
                                                      'description': 'New display name'},
                                             'model': {'type': 'string',
                                                       'description': 'New LLM model name'},
                                             'base_url': {'type': 'string',
                                                          'description': 'New LLM API base URL'},
                                             'api_key': {'type': 'string',
                                                         'description': 'New LLM API key'}},
                              'required': ['trader_id']}}},
 {'type': 'function',
  'function': {'name': 'update_program_binding',
               'description': "Update a program binding's configuration (signal pools, trigger "
                              'interval, activation, params).',
               'parameters': {'type': 'object',
                              'properties': {'binding_id': {'type': 'integer',
                                                            'description': 'Program binding ID'},
                                             'signal_pool_ids': {'type': 'array',
                                                                 'items': {'type': 'integer'},
                                                                 'description': 'New signal pool '
                                                                                'IDs'},
                                             'trigger_interval': {'type': 'integer',
                                                                  'description': 'New trigger '
                                                                                 'interval in '
                                                                                 'seconds'},
                                             'scheduled_trigger_enabled': {'type': 'boolean',
                                                                           'description': 'Enable/disable '
                                                                                          'scheduled '
                                                                                          'trigger'},
                                             'is_active': {'type': 'boolean',
                                                           'description': 'Activate or deactivate '
                                                                          'the binding'},
                                             'params_override': {'type': 'object',
                                                                 'description': 'Parameter '
                                                                                'overrides for the '
                                                                                'program'}},
                              'required': ['binding_id']}}},
 {'type': 'function',
  'function': {'name': 'update_signal_pool',
               'description': 'Update signal pool settings (name, enabled, logic, signal_ids). '
                              'Signal IDs must belong to the same exchange as the pool.',
               'parameters': {'type': 'object',
                              'properties': {'pool_id': {'type': 'integer',
                                                         'description': 'Signal pool ID'},
                                             'pool_name': {'type': 'string',
                                                           'description': 'New display name'},
                                             'enabled': {'type': 'boolean',
                                                         'description': 'Enable or disable the '
                                                                        'pool'},
                                             'logic': {'type': 'string',
                                                       'enum': ['AND', 'OR'],
                                                       'description': 'Logic operator'},
                                             'signal_ids': {'type': 'array',
                                                            'items': {'type': 'integer'},
                                                            'description': 'Replace signal '
                                                                           'definitions in this '
                                                                           'pool. All signals must '
                                                                           "match the pool's "
                                                                           'exchange.'}},
                              'required': ['pool_id']}}},
 {'type': 'function',
  'function': {'name': 'update_prompt_binding',
               'description': 'Update which prompt template is bound to an AI Trader. Replaces the '
                              'current binding.',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID'},
                                             'prompt_id': {'type': 'integer',
                                                           'description': 'New prompt template ID '
                                                                          'to bind'}},
                              'required': ['trader_id', 'prompt_id']}}},
 {'type': 'function',
  'function': {'name': 'run_dream_review',
               'description': 'Manually force or inspect one Hyper AI dream review. The real '
                              'Auto Dream service also runs in the background with time/session '
                              'gates; use this tool when the user asks to run it now, debug it, or '
                              'see what it would consolidate. It must not place trades or change '
                              'trader configuration; its only write is memory extraction when '
                              'save_memories is true.',
               'parameters': {'type': 'object',
                              'properties': {'conversation_id': {'type': 'integer',
                                                                 'description': 'Optional Hyper AI '
                                                                                'conversation ID '
                                                                                'to review. If '
                                                                                'omitted, recent '
                                                                                'conversations are '
                                                                                'reviewed.'},
                                             'conversation_ids': {'type': 'array',
                                                                  'items': {'type': 'integer'},
                                                                  'description': 'Optional list of '
                                                                                 'conversation IDs '
                                                                                 'to review. Used '
                                                                                 'by Auto Dream '
                                                                                 'after its session '
                                                                                 'gate selects '
                                                                                 'recently touched '
                                                                                 'conversations.'},
                                             'hours': {'type': 'integer',
                                                       'description': 'Recent time window to '
                                                                      'review when conversation_id '
                                                                      'is omitted. Default 24, '
                                                                      'max 168.',
                                                       'default': 24},
                                             'max_messages': {'type': 'integer',
                                                              'description': 'Maximum messages to '
                                                                             'include in the '
                                                                             'review. Default 80, '
                                                                             'max 200.',
                                                              'default': 80},
                                             'save_memories': {'type': 'boolean',
                                                               'description': 'Whether to extract '
                                                                              'and deduplicate '
                                                                              'long-term memories '
                                                                              'from the reviewed '
                                                                              'context. Default '
                                                                              'true.',
                                                               'default': True},
                                             'wait_for_memory_write': {'type': 'boolean',
                                                                       'description': 'Wait for '
                                                                                      'memory '
                                                                                      'extraction '
                                                                                      'inline. '
                                                                                      'Default '
                                                                                      'false so '
                                                                                      'the dream '
                                                                                      'task runs '
                                                                                      'in the AI '
                                                                                      'background '
                                                                                      'executor.',
                                                                      'default': False}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'run_safe_project_repair',
               'description': 'Run a whitelisted low-risk runtime repair after '
                              'inspect_project_health suggests it. This is the safe Hyper AI '
                              'repair path: it can refresh/restart Binance data collectors against '
                              'the current watchlist, but it cannot run shell commands, edit source '
                              'files, change credentials, switch environments, or place trades.',
               'parameters': {'type': 'object',
                              'properties': {'action': {'type': 'string',
                                                        'enum': ['auto',
                                                                 'refresh_binance_collectors',
                                                                 'restart_binance_kline_ws',
                                                                 'restart_binance_trade_ws'],
                                                        'description': 'Repair action to run. Use '
                                                                       'auto for the standard '
                                                                       'collector refresh repair.'},
                                             'dry_run': {'type': 'boolean',
                                                         'description': 'If true, show what would '
                                                                        'be done without changing '
                                                                        'runtime collectors. '
                                                                        'Default false.',
                                                         'default': False},
                                             'reason': {'type': 'string',
                                                        'description': 'Short reason from the user '
                                                                       'or diagnostic result.'}},
                              'required': ['action']}}},
 {'type': 'function',
  'function': {'name': 'write_project_file',
               'description': 'Operator mode: create or replace a non-secret project file in the '
                              'live workspace. Use after read_project_file and focused diagnosis. '
                              'Automatically writes a timestamped backup before replacing an '
                              'existing file. Blocks .env, keys, private VPN subscription files, '
                              '.git, node_modules, and virtualenv paths.',
               'parameters': {'type': 'object',
                              'properties': {'path': {'type': 'string',
                                                       'description': 'Project-relative or '
                                                                      'absolute path under '
                                                                      '/root/Hyper-Alpha-Arena'},
                                             'content': {'type': 'string',
                                                         'description': 'Complete UTF-8 file '
                                                                        'content to write.'},
                                             'expected_sha256': {'type': 'string',
                                                                 'description': 'Optional current '
                                                                                'file sha256 from '
                                                                                'read_project_file '
                                                                                'to avoid '
                                                                                'overwriting a '
                                                                                'changed file.'},
                                             'create': {'type': 'boolean',
                                                        'description': 'Allow creating the file if '
                                                                       'it does not exist. '
                                                                       'Default false.',
                                                        'default': False},
                                             'reason': {'type': 'string',
                                                        'description': 'Short reason for the code '
                                                                       'change.'}},
                              'required': ['path', 'content']}}},
 {'type': 'function',
  'function': {'name': 'run_project_command',
               'description': 'Operator mode: run an engineering command inside the project for '
                              'diagnosis or verification, such as rg, git diff/status, py_compile, '
                              'pytest, frontend build, localhost health checks. Destructive '
                              'commands, secret reads, external curl, database wipes, and shell '
                              'install pipes are blocked.',
               'parameters': {'type': 'object',
                              'properties': {'command': {'type': 'string',
                                                         'description': 'Shell command to run in '
                                                                        'the project workspace.'},
                                             'working_dir': {'type': 'string',
                                                             'description': 'Project-relative '
                                                                            'working directory. '
                                                                            'Default project root.',
                                                             'default': '.'},
                                             'timeout_seconds': {'type': 'integer',
                                                                 'description': 'Timeout seconds. '
                                                                                'Default 60, max '
                                                                                '180.',
                                                                 'default': 60},
                                             'reason': {'type': 'string',
                                                        'description': 'Short reason for running '
                                                                       'the command.'}},
                              'required': ['command']}}},
 {'type': 'function',
  'function': {'name': 'restart_backend_service',
               'description': 'Operator mode: schedule a graceful restart of the FastAPI backend '
                              'on port 8802 after a verified code change. Use only after syntax '
                              'checks/build checks pass. The current Hyper AI stream may disconnect '
                              'during restart.',
               'parameters': {'type': 'object',
                              'properties': {'reason': {'type': 'string',
                                                        'description': 'Short reason for the '
                                                                       'restart.'},
                                             'delay_seconds': {'type': 'integer',
                                                               'description': 'Delay before '
                                                                              'restart. Default 2, '
                                                                              'max 20.',
                                                               'default': 2}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'save_memory',
               'description': 'Save or update long-term memory with intelligent deduplication. The '
                              'system automatically compares against existing memories and decides '
                              'to ADD, UPDATE (merge/replace), or SKIP. To update an existing '
                              'memory, just call this with the corrected content — the old version '
                              'will be replaced automatically.',
               'parameters': {'type': 'object',
                              'properties': {'category': {'type': 'string',
                                                          'enum': ['preference',
                                                                   'decision',
                                                                   'lesson',
                                                                   'insight',
                                                                   'context'],
                                                          'description': 'Memory category: '
                                                                         'preference (trading '
                                                                         'style/risk), decision '
                                                                         '(config changes), lesson '
                                                                         '(from wins/losses), '
                                                                         'insight (market '
                                                                         'patterns), context '
                                                                         '(general)'},
                                             'content': {'type': 'string',
                                                         'description': 'Concise, self-contained '
                                                                        'memory content. Should be '
                                                                        'understandable without '
                                                                        'conversation context.'},
                                             'importance': {'type': 'number',
                                                            'description': 'Importance score '
                                                                           '0.0-1.0. Default 0.5. '
                                                                           'Use 0.7+ for key '
                                                                           'lessons/preferences, '
                                                                           '0.3 for minor '
                                                                           'context.'}},
                              'required': ['category', 'content']}}},
 {'type': 'function',
  'function': {'name': 'delete_trader',
               'description': 'Soft-delete an AI Trader. Checks for bindings and open positions '
                              'first. Returns dependency list if blocked.',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID to '
                                                                          'delete'}},
                              'required': ['trader_id']}}},
 {'type': 'function',
  'function': {'name': 'delete_prompt_template',
               'description': 'Soft-delete a Prompt Template. Checks for active bindings first.',
               'parameters': {'type': 'object',
                              'properties': {'prompt_id': {'type': 'integer',
                                                           'description': 'Prompt Template ID to '
                                                                          'delete'}},
                              'required': ['prompt_id']}}},
 {'type': 'function',
  'function': {'name': 'delete_signal_definition',
               'description': 'Soft-delete a Signal Definition. Checks for signal pool references '
                              'first.',
               'parameters': {'type': 'object',
                              'properties': {'signal_id': {'type': 'integer',
                                                           'description': 'Signal Definition ID to '
                                                                          'delete'}},
                              'required': ['signal_id']}}},
 {'type': 'function',
  'function': {'name': 'delete_signal_pool',
               'description': 'Soft-delete a Signal Pool. Checks for strategy and program binding '
                              'references first.',
               'parameters': {'type': 'object',
                              'properties': {'pool_id': {'type': 'integer',
                                                         'description': 'Signal Pool ID to '
                                                                        'delete'}},
                              'required': ['pool_id']}}},
 {'type': 'function',
  'function': {'name': 'delete_trading_program',
               'description': 'Soft-delete a Trading Program. Checks for active bindings first.',
               'parameters': {'type': 'object',
                              'properties': {'program_id': {'type': 'integer',
                                                            'description': 'Trading Program ID to '
                                                                           'delete'}},
                              'required': ['program_id']}}},
 {'type': 'function',
  'function': {'name': 'delete_prompt_binding',
               'description': 'Soft-delete a Prompt Binding (unbind prompt from trader).',
               'parameters': {'type': 'object',
                              'properties': {'binding_id': {'type': 'integer',
                                                            'description': 'Prompt Binding ID to '
                                                                           'delete'}},
                              'required': ['binding_id']}}},
 {'type': 'function',
  'function': {'name': 'delete_program_binding',
               'description': 'Soft-delete a Program Binding. Must be deactivated '
                              '(is_active=false) first.',
               'parameters': {'type': 'object',
                              'properties': {'binding_id': {'type': 'integer',
                                                            'description': 'Program Binding ID to '
                                                                           'delete'}},
                              'required': ['binding_id']}}}]
