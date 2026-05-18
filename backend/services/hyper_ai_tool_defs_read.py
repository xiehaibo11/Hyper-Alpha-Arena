"""Read-only and diagnostic Hyper AI tool definitions."""

READ_ONLY_TOOLS = [{'type': 'function',
  'function': {'name': 'get_system_overview',
               'description': 'Get high-level system status: wallets, AI traders, strategies, '
                              'signal pools, positions.',
               'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_robot_architecture',
               'description': 'Inspect Hyper AI main robot architecture: agent loop, tool registry, '
                              'risk metadata, sub-agent wiring, runtime stream tasks, persistence, '
                              'dream review wiring, and Claude-architecture-inspired improvements. Use this when the '
                              'user asks whether the robot/Hyper AI is working, how the AI system '
                              'is structured, or what needs improvement.',
               'parameters': {'type': 'object',
                              'properties': {'include_recent_activity': {'type': 'boolean',
                                                                         'description': 'Include '
                                                                                        'recent DB '
                                                                                        'activity '
                                                                                        'counts '
                                                                                        '(default: '
                                                                                        'true)',
                                                                         'default': True}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_wallet_status',
               'description': 'Get wallet balance and position summary (read-only, no credentials '
                              'exposed).',
               'parameters': {'type': 'object',
                              'properties': {'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx', 'all'],
                                                          'description': 'Filter by exchange '
                                                                         '(default: all)'},
                                             'environment': {'type': 'string',
                                                             'enum': ['testnet', 'mainnet', 'all'],
                                                             'description': 'Filter by environment '
                                                                            '(default: all)'}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_api_reference',
               'description': 'Get API reference docs for Prompt variables or Program '
                              'MarketData/Decision APIs.',
               'parameters': {'type': 'object',
                              'properties': {'doc_type': {'type': 'string',
                                                          'enum': ['prompt', 'program'],
                                                          'description': 'Document type: prompt '
                                                                         '(variables) or program '
                                                                         '(MarketData/Decision '
                                                                         'API)'},
                                             'api_type': {'type': 'string',
                                                          'enum': ['market', 'decision', 'all'],
                                                          'description': 'For program only: which '
                                                                         'API docs (default: all)'},
                                             'lang': {'type': 'string',
                                                      'enum': ['en', 'zh'],
                                                      'description': 'Language (default: en)'}},
                              'required': ['doc_type']}}},
 {'type': 'function',
  'function': {'name': 'get_klines',
               'description': 'Get K-line/candlestick data for a symbol.',
               'parameters': {'type': 'object',
                              'properties': {'symbol': {'type': 'string',
                                                        'description': 'Trading symbol (e.g., BTC, '
                                                                       'ETH)'},
                                             'period': {'type': 'string',
                                                        'enum': ['1m',
                                                                 '5m',
                                                                 '15m',
                                                                 '1h',
                                                                 '4h',
                                                                 '1d'],
                                                        'description': 'K-line period (default: '
                                                                       '1h)'},
                                             'limit': {'type': 'integer',
                                                       'description': 'Number of candles (default: '
                                                                      '50, max: 200)'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange (default: '
                                                                         'hyperliquid)'}},
                              'required': ['symbol']}}},
 {'type': 'function',
  'function': {'name': 'get_market_regime',
               'description': 'Get current market regime classification for a symbol.',
               'parameters': {'type': 'object',
                              'properties': {'symbol': {'type': 'string',
                                                        'description': 'Trading symbol'},
                                             'period': {'type': 'string',
                                                        'enum': ['1m',
                                                                 '5m',
                                                                 '15m',
                                                                 '1h',
                                                                 '4h',
                                                                 '1d'],
                                                        'description': 'Time period (default: 1h)'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange (default: '
                                                                         'hyperliquid)'}},
                              'required': ['symbol']}}},
 {'type': 'function',
  'function': {'name': 'get_market_flow',
               'description': 'Get market flow data (CVD, OI, Funding, etc.) for a symbol.',
               'parameters': {'type': 'object',
                              'properties': {'symbol': {'type': 'string',
                                                        'description': 'Trading symbol'},
                                             'period': {'type': 'string',
                                                        'enum': ['1m',
                                                                 '5m',
                                                                 '15m',
                                                                 '1h',
                                                                 '4h',
                                                                 '1d'],
                                                        'description': 'Time period (default: 1h)'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange (default: '
                                                                         'hyperliquid)'}},
                              'required': ['symbol']}}},
 {'type': 'function',
  'function': {'name': 'get_system_logs',
               'description': 'Get recent system logs enriched with error registry (severity, '
                              "exchange relevance, suggestions). Logs marked 'other_exchange' are "
                              "from an exchange the user doesn't use — deprioritize them.",
               'parameters': {'type': 'object',
                              'properties': {'level': {'type': 'string',
                                                       'enum': ['error', 'warning', 'all'],
                                                       'description': 'Log level filter (default: '
                                                                      'error)'},
                                             'limit': {'type': 'integer',
                                                       'description': 'Max entries (default: 20, '
                                                                      'max: 50)'},
                                             'trader_id': {'type': 'integer',
                                                           'description': 'Filter by AI Trader '
                                                                          'ID'}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_contact_config',
               'description': 'Get support channel URLs (Twitter, Telegram, GitHub).',
               'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_trading_environment',
               'description': 'Get current global trading environment (testnet/mainnet). This '
                              'affects which wallets and data sources are used system-wide.',
               'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_watchlist',
               'description': 'Get symbol watchlist configuration for all exchanges. Shows which '
                              'symbols are being monitored for data collection and trading. Also '
                              'indicates if user is still using default symbols.',
               'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
 {'type': 'function',
  'function': {'name': 'plan_trading_goal',
               'description': "Analyze a user's capital/target/time trading goal before creating "
                              'strategy components. Returns feasibility, missing constraints, '
                              'required confirmations, and an automation workflow. Read-only; does '
                              'not trade or modify configuration.',
               'parameters': {'type': 'object',
                              'properties': {'starting_capital': {'type': 'number',
                                                                  'description': 'Starting capital '
                                                                                 'in USDT or USD, '
                                                                                 'if user provided '
                                                                                 'it.'},
                                             'target_capital': {'type': 'number',
                                                                'description': 'Target capital in '
                                                                               'USDT or USD, if '
                                                                               'user provided it.'},
                                             'time_horizon_days': {'type': 'number',
                                                                   'description': 'Goal horizon in '
                                                                                  'days. Convert '
                                                                                  'phrases like '
                                                                                  'half a month to '
                                                                                  '15 when '
                                                                                  'possible.'},
                                             'time_horizon_text': {'type': 'string',
                                                                   'description': 'Raw user '
                                                                                  'horizon text '
                                                                                  'when it is '
                                                                                  'ambiguous, e.g. '
                                                                                  "'half month' or "
                                                                                  "'two weeks'."},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid',
                                                                   'binance',
                                                                   'unknown'],
                                                          'description': 'Exchange requested by '
                                                                         'user. Use unknown if not '
                                                                         'specified.'},
                                             'environment': {'type': 'string',
                                                             'enum': ['testnet',
                                                                      'mainnet',
                                                                      'unknown'],
                                                             'description': 'Trading environment '
                                                                            'requested by user. '
                                                                            'Use unknown if not '
                                                                            'specified.'},
                                             'max_loss': {'type': 'number',
                                                          'description': 'Maximum loss the user '
                                                                         'accepts in USDT, if '
                                                                         'specified.'},
                                             'risk_mode': {'type': 'string',
                                                           'enum': ['conservative',
                                                                    'balanced',
                                                                    'aggressive',
                                                                    'unknown'],
                                                           'description': 'User risk preference.'},
                                             'preferred_symbols': {'type': 'array',
                                                                   'items': {'type': 'string'},
                                                                   'description': 'Symbols the '
                                                                                  'user wants to '
                                                                                  'trade, e.g. '
                                                                                  "['BTC', "
                                                                                  "'ETH']."},
                                             'strategy_type': {'type': 'string',
                                                               'enum': ['prompt',
                                                                        'program',
                                                                        'unknown'],
                                                               'description': "User's preferred "
                                                                              'strategy type.'},
                                             'existing_trader_id': {'type': 'integer',
                                                                    'description': 'AI Trader ID '
                                                                                   'if the user '
                                                                                   'explicitly '
                                                                                   'wants to use '
                                                                                   'an existing '
                                                                                   'trader.'},
                                             'notes': {'type': 'string',
                                                       'description': 'Any other user-provided '
                                                                      'objective or constraints.'}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'update_watchlist',
               'description': 'Update symbol watchlist for a specific exchange. IMPORTANT: Always '
                              'call get_watchlist first to show current config and get user '
                              'confirmation before updating.',
               'parameters': {'type': 'object',
                              'properties': {'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange to update '
                                                                         'watchlist for'},
                                             'symbols': {'type': 'array',
                                                         'items': {'type': 'string'},
                                                         'description': 'List of symbols to '
                                                                        "monitor (e.g., ['BTC', "
                                                                        "'ETH', 'SOL']). Max 10 "
                                                                        'symbols.'}},
                              'required': ['exchange', 'symbols']}}},
 {'type': 'function',
  'function': {'name': 'diagnose_trader_issues',
               'description': 'Check why an AI Trader is not triggering and provide actionable '
                              'suggestions.',
               'parameters': {'type': 'object',
                              'properties': {'trader_id': {'type': 'integer',
                                                           'description': 'AI Trader ID to '
                                                                          'diagnose'}},
                              'required': ['trader_id']}}},
 {'type': 'function',
  'function': {'name': 'inspect_project_health',
               'description': 'Inspect live project health like a coding assistant: runtime '
                              'process status, Binance collector/watchlist alignment, recent '
                              'warnings/errors, AI decision anomalies, and safe repair '
                              'recommendations. Read-only; does not restart collectors or edit '
                              'files.',
               'parameters': {'type': 'object',
                              'properties': {'scope': {'type': 'string',
                                                       'enum': ['all',
                                                                'binance',
                                                                'hyper_ai',
                                                                'trading'],
                                                       'description': 'Diagnostic scope. Default: '
                                                                      'all',
                                                       'default': 'all'},
                                             'include_logs': {'type': 'boolean',
                                                              'description': 'Include recent '
                                                                             'warning/error logs. '
                                                                             'Default: true',
                                                              'default': True},
                                             'log_limit': {'type': 'integer',
                                                           'description': 'Maximum recent logs to '
                                                                          'inspect. Default 30, '
                                                                          'max 80.',
                                                          'default': 30}},
                              'required': []}}},
 {'type': 'function',
  'function': {'name': 'read_project_file',
               'description': 'Operator mode: read a non-secret project file from the live server '
                              'workspace for engineering diagnosis. Blocks .env, keys, private '
                              'VPN subscription files, .git, node_modules, and virtualenv paths.',
               'parameters': {'type': 'object',
                              'properties': {'path': {'type': 'string',
                                                       'description': 'Project-relative or '
                                                                      'absolute path under '
                                                                      '/root/Hyper-Alpha-Arena'},
                                             'start_line': {'type': 'integer',
                                                            'description': '1-based first line. '
                                                                           'Default 1.',
                                                            'default': 1},
                                             'end_line': {'type': 'integer',
                                                          'description': 'Optional 1-based last '
                                                                         'line.'},
                                             'max_chars': {'type': 'integer',
                                                           'description': 'Maximum characters to '
                                                                          'return. Default 20000, '
                                                                          'max 60000.',
                                                           'default': 20000}},
                              'required': ['path']}}},
 {'type': 'function',
  'function': {'name': 'analyze_tracked_address',
               'description': 'Get private Hyper Insight address detail for a tracked wallet. '
                              'Returns factual data for recent activity analysis; recent fills are '
                              "limited and do not represent the wallet's complete all-time trade "
                              'history.',
               'parameters': {'type': 'object',
                              'properties': {'address': {'type': 'string',
                                                         'description': 'Tracked wallet address to '
                                                                        'analyze'}},
                              'required': ['address']}}},
 {'type': 'function',
  'function': {'name': 'get_tracked_wallets',
               'description': 'Get the current Hyper Insight wallet sync status and the tracked '
                              'wallet addresses currently synced into Hyper Alpha Arena. Use this '
                              'to see whether Hyper Insight is connected and which wallets are '
                              'currently available to wallet-tracking signal pools.',
               'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
 {'type': 'function',
  'function': {'name': 'get_strategy_radar_universe',
               'description': "Get Strategy Radar's currently supported "
                              'symbol/period/exchange/regime combinations. Call before searching '
                              'Strategy Radar so unsupported symbols are not inferred.',
               'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
 {'type': 'function',
  'function': {'name': 'search_strategy_radar',
               'description': 'Search current Strategy Radar candidates for a supported symbol and '
                              'period. Results are quality-filtered strategy ideas, not '
                              'profitability rankings.',
               'parameters': {'type': 'object',
                              'properties': {'symbol': {'type': 'string',
                                                        'description': 'Supported trading symbol '
                                                                       'from '
                                                                       'get_strategy_radar_universe, '
                                                                       'e.g. BTC'},
                                             'period': {'type': 'string',
                                                        'enum': ['1h', '4h', '1d'],
                                                        'description': 'Radar period (default: '
                                                                       '1h)'},
                                             'regime': {'type': 'string',
                                                        'description': 'Optional requested regime. '
                                                                       'Omit to use current Radar '
                                                                       'regime for the '
                                                                       'symbol/period.'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Optional exchange '
                                                                         'filter'},
                                             'strategy_type': {'type': 'string',
                                                               'description': 'Optional strategy '
                                                                              'type filter'},
                                             'sort_by': {'type': 'string',
                                                         'enum': ['relevance', 'quality', 'newest'],
                                                         'description': 'Optional sort mode. '
                                                                        'Default is relevance.'},
                                             'risk_level': {'type': 'string',
                                                            'enum': ['Low', 'Medium', 'High'],
                                                            'description': 'Optional risk filter.'},
                                             'timeframe': {'type': 'string',
                                                           'enum': ['1h', '4h', '1d', 'multi'],
                                                           'description': 'Optional card timeframe '
                                                                          'filter.'},
                                             'limit': {'type': 'integer',
                                                       'description': 'Max results (default: 5, '
                                                                      'max: 10)'}},
                              'required': ['symbol']}}}]
