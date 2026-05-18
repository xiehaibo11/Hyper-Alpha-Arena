"""Account LLM connectivity API routes."""

import logging

from fastapi import APIRouter

from services.ai_decision_service import (
    build_chat_completion_endpoints,
    build_llm_headers,
    detect_api_format,
    is_new_openai_model,
    is_reasoning_model,
    _extract_text_from_message,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/test-llm")
def test_llm_connection(payload: dict):
    """Test LLM connection with provided credentials"""
    try:
        import requests
        import json

        model = payload.get("model", "gpt-3.5-turbo")
        base_url = payload.get("base_url", "https://api.openai.com/v1")
        api_key = payload.get("api_key", "")

        if not api_key:
            return {"success": False, "message": "API key is required"}

        if not base_url:
            return {"success": False, "message": "Base URL is required"}

        # Clean up base_url - ensure it doesn't end with slash
        if base_url.endswith('/'):
            base_url = base_url.rstrip('/')

        # Detect API format from URL
        endpoint, api_format = detect_api_format(base_url)
        if not endpoint:
            return {"success": False, "message": "Invalid base URL"}

        # Test the connection with a simple completion request
        try:
            model_lower = model.lower()
            is_reasoning = is_reasoning_model(model)
            is_o1_series = any(x in model_lower for x in ['o1-preview', 'o1-mini', 'o1-', 'o1'])
            is_new_model = is_new_openai_model(model)

            if api_format == 'anthropic':
                # Anthropic native format
                headers = build_llm_headers(api_format, api_key, endpoint)
                payload_data = {
                    "model": model,
                    "max_tokens": 1024,
                    "messages": [
                        {"role": "user", "content": "Say 'Connection test successful' if you can read this."}
                    ]
                }
            else:
                # OpenAI compatible format
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                if is_o1_series:
                    payload_data = {
                        "model": model,
                        "messages": [
                            {"role": "user", "content": "Say 'Connection test successful' if you can read this."}
                        ]
                    }
                else:
                    payload_data = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are a helpful assistant."},
                            {"role": "user", "content": "Say 'Connection test successful' if you can read this."}
                        ]
                    }

                if not is_reasoning:
                    payload_data["temperature"] = 0

                if is_new_model:
                    payload_data["max_completion_tokens"] = 2000
                else:
                    payload_data["max_tokens"] = 2000

                if 'gpt-5' in model_lower:
                    payload_data["reasoning_effort"] = "low"

            # For Anthropic format, use the detected endpoint directly
            # For OpenAI format, use build_chat_completion_endpoints for fallback support
            if api_format == 'anthropic':
                endpoints_to_try = [endpoint]
            else:
                endpoints_to_try = build_chat_completion_endpoints(base_url, model)
                if not endpoints_to_try:
                    return {"success": False, "message": "Invalid base URL"}

            last_failure_message = "Connection test failed"

            for idx, ep in enumerate(endpoints_to_try):
                try:
                    response = requests.post(
                        ep,
                        headers=headers,
                        json=payload_data,
                        timeout=10.0,
                        verify=False
                    )
                except requests.ConnectionError:
                    last_failure_message = f"Failed to connect to {ep}. Please check the base URL."
                    continue
                except requests.Timeout:
                    last_failure_message = "Request timed out. The LLM service may be unavailable."
                    continue
                except requests.RequestException as req_err:
                    last_failure_message = f"Connection test failed: {str(req_err)}"
                    continue

                # Check response status
                if response.status_code == 200:
                    result = response.json()

                    if api_format == 'anthropic':
                        # Anthropic response format: {"content": [{"type": "text", "text": "..."}], ...}
                        content_list = result.get("content", [])
                        content = ""
                        for item in content_list:
                            if isinstance(item, dict) and item.get("type") == "text":
                                content = item.get("text", "")
                                break
                        if content:
                            logger.info(f"LLM test successful for model {model} at {ep} (Anthropic format)")
                            return {
                                "success": True,
                                "message": f"Connection successful! Model {model} responded correctly (Anthropic API).",
                                "response": content
                            }
                        else:
                            return {"success": False, "message": "Anthropic API responded but with empty content."}
                    else:
                        # OpenAI-compatible response format
                        if "choices" in result and len(result["choices"]) > 0:
                            choice = result["choices"][0]
                            message = choice.get("message", {})
                            finish_reason = choice.get("finish_reason", "")

                            raw_content = message.get("content")
                            content = _extract_text_from_message(raw_content)

                            if not content and is_reasoning:
                                reasoning = _extract_text_from_message(message.get("reasoning"))
                                if reasoning:
                                    logger.info(f"LLM test successful for model {model} at {ep} (reasoning model)")
                                    snippet = reasoning[:100] + "..." if len(reasoning) > 100 else reasoning
                                    return {
                                        "success": True,
                                        "message": f"Connection successful! Model {model} (reasoning model) responded correctly.",
                                        "response": f"[Reasoning: {snippet}]"
                                    }

                            if content:
                                logger.info(f"LLM test successful for model {model} at {ep}")
                                return {
                                    "success": True,
                                    "message": f"Connection successful! Model {model} responded correctly.",
                                    "response": content
                                }

                            logger.warning(f"LLM response has empty content. finish_reason={finish_reason}, full_message={message}")
                            return {
                                "success": False,
                                "message": f"LLM responded but with empty content (finish_reason: {finish_reason}). Try increasing token limit or using a different model."
                            }
                        else:
                            return {"success": False, "message": "Unexpected response format from LLM"}
                elif response.status_code == 401:
                    return {"success": False, "message": "Authentication failed. Please check your API key."}
                elif response.status_code == 403:
                    return {"success": False, "message": "Permission denied. Your API key may not have access to this model."}
                elif response.status_code == 429:
                    return {"success": False, "message": "Rate limit exceeded. Please try again later."}
                elif response.status_code == 404:
                    last_failure_message = f"Model '{model}' not found or endpoint not available."
                    if idx < len(endpoints_to_try) - 1:
                        logger.info(f"Endpoint {ep} returned 404, trying alternative path")
                        continue
                    return {"success": False, "message": last_failure_message}
                else:
                    return {"success": False, "message": f"API returned status {response.status_code}: {response.text}"}

            return {"success": False, "message": last_failure_message}

        except requests.ConnectionError:
            return {"success": False, "message": f"Failed to connect to {base_url}. Please check the base URL."}
        except requests.Timeout:
            return {"success": False, "message": "Request timed out. The LLM service may be unavailable."}
        except json.JSONDecodeError:
            return {"success": False, "message": "Invalid JSON response from LLM service."}
        except requests.RequestException as e:
            logger.error(f"LLM test request failed: {e}", exc_info=True)
            return {"success": False, "message": f"Connection test failed: {str(e)}"}
        except Exception as e:
            logger.error(f"LLM test failed: {e}", exc_info=True)
            return {"success": False, "message": f"Connection test failed: {str(e)}"}

    except Exception as e:
        logger.error(f"Failed to test LLM connection: {e}", exc_info=True)
        return {"success": False, "message": f"Failed to test LLM connection: {str(e)}"}
