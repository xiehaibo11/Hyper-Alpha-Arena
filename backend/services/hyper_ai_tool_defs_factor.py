"""Factor-system Hyper AI tool definitions."""

FACTOR_TOOLS = [{'type': 'function',
  'function': {'name': 'query_factors',
               'description': 'Query factor library and effectiveness data. Without symbol: '
                              'returns factor list. With symbol: returns factor values and '
                              'effectiveness ranking. Fields: decay_half_life_hours (spatial '
                              'dimension): positive=half-life in hours (IC decays across forward '
                              'periods), -1=persistent (IC holds across periods). ic_7d: average '
                              'IC over recent 7 days. ic_trend (temporal dimension): ic_7d / '
                              'ic_30d ratio, >1 = factor strengthening recently, <1 = weakening, '
                              'helps detect if factor is losing effectiveness over time.',
               'parameters': {'type': 'object',
                              'properties': {'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange (required)'},
                                             'symbol': {'type': 'string',
                                                        'description': 'Trading symbol (e.g., '
                                                                       'BTC). If omitted, returns '
                                                                       'factor library list.'},
                                             'factor_name': {'type': 'string',
                                                             'description': 'Specific factor name '
                                                                            'for detailed info + '
                                                                            'history'},
                                             'forward_period': {'type': 'string',
                                                                'enum': ['1h', '4h', '12h', '24h'],
                                                                'description': 'Forward period for '
                                                                               'effectiveness '
                                                                               '(default: 4h)'},
                                             'days': {'type': 'integer',
                                                      'description': 'Number of days of history to '
                                                                     'return when querying a '
                                                                     'specific factor (default: '
                                                                     '30, max: 365). Use larger '
                                                                     'values for long-term trend '
                                                                     'analysis.'}},
                              'required': ['exchange']}}},
 {'type': 'function',
  'function': {'name': 'evaluate_factor',
               'description': 'Evaluate a custom factor expression against real market data. '
                              'Returns syntax validation, latest value, and IC/ICIR/win_rate for '
                              'each forward period.',
               'parameters': {'type': 'object',
                              'properties': {'expression': {'type': 'string',
                                                            'description': 'Factor expression '
                                                                           "(e.g., 'EMA(close, 7) "
                                                                           '/ EMA(close, 21) - '
                                                                           "1')"},
                                             'symbol': {'type': 'string',
                                                        'description': 'Trading symbol (e.g., '
                                                                       'BTC)'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange (required)'}},
                              'required': ['expression', 'symbol', 'exchange']}}},
 {'type': 'function',
  'function': {'name': 'save_factor',
               'description': 'Save a custom factor expression to the factor library.',
               'parameters': {'type': 'object',
                              'properties': {'name': {'type': 'string',
                                                      'description': 'Factor name (unique, '
                                                                     'descriptive)'},
                                             'expression': {'type': 'string',
                                                            'description': 'Factor expression'},
                                             'description': {'type': 'string',
                                                             'description': 'Brief description of '
                                                                            'what the factor '
                                                                            'measures'}},
                              'required': ['name', 'expression']}}},
 {'type': 'function',
  'function': {'name': 'edit_factor',
               'description': 'Edit an existing custom factor. Only custom factors can be edited, '
                              'not built-in ones.',
               'parameters': {'type': 'object',
                              'properties': {'factor_id': {'type': 'integer',
                                                           'description': 'Custom factor ID '
                                                                          '(required)'},
                                             'name': {'type': 'string',
                                                      'description': 'New name (optional)'},
                                             'expression': {'type': 'string',
                                                            'description': 'New expression '
                                                                           '(optional)'},
                                             'description': {'type': 'string',
                                                             'description': 'New description '
                                                                            '(optional)'}},
                              'required': ['factor_id']}}},
 {'type': 'function',
  'function': {'name': 'compute_factor',
               'description': 'Run computation for a specific factor across all watchlist symbols '
                              'on an exchange. Updates factor values and effectiveness metrics.',
               'parameters': {'type': 'object',
                              'properties': {'factor_name': {'type': 'string',
                                                             'description': 'Factor name to '
                                                                            'compute'},
                                             'exchange': {'type': 'string',
                                                          'enum': ['hyperliquid', 'binance', 'okx'],
                                                          'description': 'Exchange (required)'}},
                              'required': ['factor_name', 'exchange']}}},
 {'type': 'function',
  'function': {'name': 'get_factor_functions',
               'description': 'Get the full list of supported factor expression functions, grouped '
                              'by category. Call this BEFORE designing or modifying factor '
                              'expressions, so you know exactly which functions are available and '
                              'their signatures.',
               'parameters': {'type': 'object',
                              'properties': {'category': {'type': 'string',
                                                          'description': 'Filter by category '
                                                                         '(optional). Leave empty '
                                                                         'for all categories.'}},
                              'required': []}}}]
